import os
import sys
import random
import string
import threading
from datetime import datetime

import tkinter as tk

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.watcher import get_watcher_state

NEON_GREEN = "#39FF14"
DIM_GREEN  = "#1a7a08"
CYAN       = "#00ffff"
BLACK      = "#000000"

RAIN_COLS      = 80
RAIN_CHAR_H    = 18
RAIN_FPS_MS    = 55
STATS_MS       = 1000

_hud_thread: threading.Thread | None = None
_stop_event   = threading.Event()
_killed_log:  list[str]      = []
_focus_start: datetime | None = None


def notify_killed(name: str) -> None:
    _killed_log.append(name)
    if len(_killed_log) > 20:
        _killed_log.pop(0)


def set_focus_start(dt: datetime) -> None:
    global _focus_start
    _focus_start = dt


def _uptime() -> str:
    if _focus_start is None:
        return "00:00:00"
    d = datetime.now() - _focus_start
    h, r = divmod(int(d.total_seconds()), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _run_hud() -> None:
    _stop_event.clear()

    try:
        root = tk.Tk()
    except Exception as e:
        print(f"[HUD] Tkinter init failed: {e}", file=sys.stderr)
        return

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    root.geometry(f"{sw}x{sh}+0+0")
    root.configure(bg=BLACK)
    root.attributes("-alpha", 0.88)
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.title("AFRO — DEEP FOCUS")
    root.bind("<Escape>", lambda _: _stop_event.set())

    canvas = tk.Canvas(root, bg=BLACK, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    # ── Matrix Rain State ───────────────────────────────────────────
    col_w  = max(1, sw // RAIN_COLS)
    drops  = [random.randint(-40, 0) for _ in range(RAIN_COLS)]
    _chars = [random.choice(string.printable[:94]) for _ in range(RAIN_COLS)]

    _TRAIL_COLORS = [
        f"#{0:02x}{max(10, 160 - t * 28):02x}{0:02x}"
        for t in range(1, 8)
    ]

    def update_rain():
        if _stop_event.is_set():
            root.destroy()
            return

        canvas.delete("rain")

        for i in range(RAIN_COLS):
            x = i * col_w + col_w // 2
            y = drops[i] * RAIN_CHAR_H
            _chars[i] = random.choice(string.printable[:94])

            # head
            canvas.create_text(x, y, text=_chars[i], fill=NEON_GREEN,
                                font=("Courier New", 11), tags="rain")
            # trail
            for t, color in enumerate(_TRAIL_COLORS, 1):
                ty = y - t * RAIN_CHAR_H
                if ty < 0:
                    break
                canvas.create_text(x, ty,
                                   text=random.choice(string.printable[:94]),
                                   fill=color, font=("Courier New", 10),
                                   tags="rain")

            drops[i] += 1
            if drops[i] * RAIN_CHAR_H > sh:
                drops[i] = random.randint(-20, 0)

        root.after(RAIN_FPS_MS, update_rain)

    # ── Status Overlay ──────────────────────────────────────────────
    def update_stats():
        if _stop_event.is_set():
            return

        canvas.delete("stat")

        state    = get_watcher_state()
        cpu      = state.get("cpu_usage", 0.0)
        vram     = state.get("gpu_vram_usage", 0.0)
        win_raw  = state.get("active_window", "—")
        win      = win_raw[:58] if len(win_raw) > 58 else win_raw
        uptime   = _uptime()
        killed   = ", ".join(_killed_log[-5:]) if _killed_log else "none"

        lines = [
            ("[ SYSTEM STATUS: ENFORCING DEEP FOCUS ]", NEON_GREEN),
            ("─" * 47,                                   DIM_GREEN),
            (f"TARGET  : {win}",                         NEON_GREEN),
            (f"VRAM    : {vram:.1f}%",                   NEON_GREEN),
            (f"CPU     : {cpu:.1f}%",                    NEON_GREEN),
            (f"UPTIME  : {uptime}",                      NEON_GREEN),
            (f"KILLED  : {killed}",                      NEON_GREEN),
            ("─" * 47,                                   DIM_GREEN),
            ("> AFRO_CORE: MONITORING...",               CYAN),
        ]

        line_h = 24
        pad    = 18
        box_w  = 580
        box_h  = len(lines) * line_h + pad * 2
        bx     = (sw - box_w) // 2
        by     = (sh - box_h) // 2

        canvas.create_rectangle(
            bx - pad, by - pad, bx + box_w + pad, by + box_h,
            fill="#000000", outline=NEON_GREEN, width=1,
            tags="stat",
        )

        for i, (text, color) in enumerate(lines):
            canvas.create_text(
                bx, by + i * line_h,
                text=text, fill=color, anchor="nw",
                font=("Courier New", 13, "bold"),
                tags="stat",
            )

        root.after(STATS_MS, update_stats)

    update_rain()
    update_stats()

    try:
        root.mainloop()
    except Exception as e:
        print(f"[HUD] mainloop error: {e}", file=sys.stderr)


def start_hud(focus_start: datetime | None = None) -> None:
    global _hud_thread
    if _hud_thread and _hud_thread.is_alive():
        return
    if focus_start is not None:
        set_focus_start(focus_start)
    else:
        set_focus_start(datetime.now())
    _stop_event.clear()
    _hud_thread = threading.Thread(target=_run_hud, daemon=True, name="AfroHUD")
    _hud_thread.start()


def stop_hud() -> None:
    _stop_event.set()
