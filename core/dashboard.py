import os
import sys
import threading
import time

import psutil
from flask import Flask, render_template
from flask_socketio import SocketIO

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.clipboard import get_text

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

_brain_feed: list[str] = []
_brain_feed_lock = threading.Lock()


def log_brain(message: str) -> None:
    with _brain_feed_lock:
        _brain_feed.append(message)
        if len(_brain_feed) > 200:
            _brain_feed.pop(0)


def _get_gpu_vram() -> float:
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return round(mem.used / mem.total * 100, 1)
    except Exception:
        return 0.0


def _telemetry_loop() -> None:
    while True:
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            gpu = _get_gpu_vram()

            with _brain_feed_lock:
                feed_snapshot = list(_brain_feed[-50:])

            clip = get_text()
            clip_preview = clip[:300] if clip else ""

            socketio.emit("telemetry", {
                "cpu": cpu,
                "ram": ram,
                "gpu": gpu,
                "brain_feed": feed_snapshot,
                "clipboard_preview": clip_preview,
            })
        except Exception as e:
            print(f"[Dashboard] Telemetry error: {e}")

        time.sleep(2)


@app.route("/")
def index():
    return render_template("index.html")


def start_dashboard() -> threading.Thread:
    t = threading.Thread(
        target=lambda: socketio.run(app, host="127.0.0.1", port=5000, use_reloader=False, log_output=False),
        daemon=True,
        name="AfroDashboard",
    )
    t.start()

    tel = threading.Thread(target=_telemetry_loop, daemon=True, name="AfroTelemetry")
    tel.start()

    return t
