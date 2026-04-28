import threading
import sys
import webbrowser

import pystray
from PIL import Image, ImageDraw

DASHBOARD_URL = "http://127.0.0.1:5000"


def _create_icon_image(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(30, 144, 255), outline=(255, 255, 255), width=2)
    draw.text((size // 2 - 8, size // 2 - 8), "A", fill=(255, 255, 255))
    return image


def _on_status(icon, item) -> None:
    print("[Afro] System active and listening.")


def _on_dashboard(icon, item) -> None:
    webbrowser.open(DASHBOARD_URL)


def _on_exit(icon, item) -> None:
    print("[Afro] Shutting down system tray...")
    icon.stop()
    sys.exit(0)


def _run_tray() -> None:
    try:
        icon_image = _create_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Status", _on_status),
            pystray.MenuItem("Show Dashboard", _on_dashboard),
            pystray.MenuItem("Exit", _on_exit),
        )
        icon = pystray.Icon(
            name="Afro",
            icon=icon_image,
            title="Afro AI Running",
            menu=menu,
        )
        icon.run()
    except Exception as e:
        print(f"[SystemTray] Failed to start: {e}")


def start_tray() -> threading.Thread:
    tray_thread = threading.Thread(target=_run_tray, daemon=True, name="AfroTray")
    tray_thread.start()
    return tray_thread
