import os
import sys
import threading
import time
from datetime import datetime

import psutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

POLL_INTERVAL = 10
VRAM_CRITICAL_PCT = 90.0
CPU_WARNING_PCT = 70.0
CPU_CRITICAL_PCT = 90.0
VSC_FOCUS_THRESHOLD_MIN = 60
VRAM_ALERT_COOLDOWN = 300
VSC_REMINDER_COOLDOWN = 3600

_state_lock = threading.Lock()
_state: dict = {
    "active_window": "",
    "focus_duration_minutes": 0,
    "cpu_usage": 0.0,
    "gpu_vram_usage": 0.0,
    "health_status": "NORMAL",
}


def get_watcher_state() -> dict:
    with _state_lock:
        return dict(_state)


def _classify_health(cpu: float, vram: float) -> str:
    if cpu > CPU_CRITICAL_PCT or vram > VRAM_CRITICAL_PCT:
        return "CRITICAL"
    if cpu > CPU_WARNING_PCT:
        return "WARNING"
    return "NORMAL"


def _get_vram_pct() -> float:
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return round(mem.used / mem.total * 100, 1)
    except Exception:
        return 0.0


def _get_active_window() -> str:
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        return win.title if win else ""
    except Exception:
        return ""


class Watcher:

    def __init__(self, synth=None):
        self._synth = synth
        self._current_window: str = ""
        self._window_start: datetime = datetime.now()
        self._last_vram_alert: float = 0.0
        self._last_vsc_reminder: float = 0.0

    def _speak(self, text: str) -> None:
        if self._synth:
            threading.Thread(target=self._synth.speak, args=(text,), daemon=True).start()
        else:
            print(f"[Watcher] {text}")

    def _check_window(self) -> None:
        title = _get_active_window()
        now = datetime.now()

        if title != self._current_window:
            self._current_window = title
            self._window_start = now

        duration_min = int((now - self._window_start).total_seconds() / 60)

        with _state_lock:
            _state["active_window"] = title
            _state["focus_duration_minutes"] = duration_min

        vsc_due = time.monotonic() - self._last_vsc_reminder > VSC_REMINDER_COOLDOWN
        if (
            "visual studio code" in title.lower()
            and duration_min >= VSC_FOCUS_THRESHOLD_MIN
            and vsc_due
        ):
            self._last_vsc_reminder = time.monotonic()
            try:
                from agents.meta_agent import run_review_on_command
                threading.Thread(target=run_review_on_command, daemon=True).start()
            except Exception as e:
                print(f"[Watcher] MetaAgent trigger failed: {e}", file=sys.stderr)
            self._speak(
                "You've been in the zone. "
                "Need a quick summary of your changes for a commit message?"
            )

    def _check_health(self) -> None:
        cpu = psutil.cpu_percent(interval=None)
        vram = _get_vram_pct()
        status = _classify_health(cpu, vram)

        with _state_lock:
            _state["cpu_usage"] = cpu
            _state["gpu_vram_usage"] = vram
            _state["health_status"] = status

        vram_due = time.monotonic() - self._last_vram_alert > VRAM_ALERT_COOLDOWN
        if vram > VRAM_CRITICAL_PCT and vram_due:
            self._last_vram_alert = time.monotonic()
            self._speak(
                "VRAM is critical. "
                "Should I purge the Whisper cache to save your display drivers?"
            )

    def _loop(self) -> None:
        while True:
            try:
                self._check_window()
                self._check_health()
            except Exception as e:
                print(f"[Watcher] Loop error: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self._loop, daemon=True, name="AfroWatcher")
        t.start()
        return t
