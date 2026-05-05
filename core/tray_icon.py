import os
import sys
import threading
import webbrowser

import pystray
from PIL import Image, ImageDraw

# ── Windows startup registry ──────────────────────────────────────────────────
_RUN_KEY   = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME  = "Afro"


def _startup_enabled() -> bool:
    """True if HKCU Run key for Afro exists."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def _set_startup(enable: bool) -> None:
    """Write or delete HKCU\\Run\\Afro."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY,
            access=winreg.KEY_SET_VALUE,
        ) as k:
            if enable:
                # frozen (PyInstaller): sys.executable = Afro.exe
                # dev: sys.executable = python.exe — acceptable for dev installs
                exe_path = sys.executable
                winreg.SetValueEx(k, _APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
                print(f"[TrayIcon] Start with Windows enabled: {exe_path!r}")
            else:
                try:
                    winreg.DeleteValue(k, _APP_NAME)
                    print("[TrayIcon] Start with Windows disabled.")
                except FileNotFoundError:
                    pass
    except Exception as e:
        print(f"[TrayIcon] Startup registry error: {e}")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

DASHBOARD_URL = "http://127.0.0.1:5000"

# Palette
_COLOR_ACTIVE = (34, 197, 94)    # neon green
_COLOR_IDLE   = (100, 116, 139)  # slate-gray
_OUTLINE      = (255, 255, 255)
_SIZE         = 64


def _make_icon(color: tuple[int, int, int]) -> Image.Image:
    img  = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad  = 4
    draw.ellipse(
        [pad, pad, _SIZE - pad, _SIZE - pad],
        fill=color, outline=_OUTLINE, width=2,
    )
    try:
        from PIL import ImageFont
        font = ImageFont.load_default()
        draw.text((_SIZE // 2 - 5, _SIZE // 2 - 7), "A", fill=_OUTLINE, font=font)
    except Exception:
        draw.text((_SIZE // 2 - 5, _SIZE // 2 - 7), "A", fill=_OUTLINE)
    return img


class TrayIconManager:
    """System tray icon with agent state reflection and full action menu."""

    def __init__(
        self,
        on_activate=None,
        on_standby=None,
        on_deep_focus=None,
        on_exit=None,
    ):
        self._on_activate   = on_activate    # callable() — activate agent
        self._on_standby    = on_standby     # callable() — put agent on standby
        self._on_deep_focus = on_deep_focus  # callable() — enter deep focus
        self._on_exit       = on_exit        # callable() — clean shutdown

        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._state = "IDLE"
        self._lock  = threading.Lock()

    # ── Icon factory ─────────────────────────────────────────────────────────

    def _icon_for_state(self) -> Image.Image:
        color = _COLOR_ACTIVE if self._state == "ACTIVE" else _COLOR_IDLE
        return _make_icon(color)

    # ── Menu callbacks ────────────────────────────────────────────────────────

    def _cb_dashboard(self, icon, item) -> None:
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception as e:
            print(f"[TrayIcon] Dashboard open error: {e}")

    def _cb_activate(self, icon, item) -> None:
        if self._on_activate:
            try:
                threading.Thread(
                    target=self._on_activate,
                    daemon=True,
                    name="AfroTrayActivate",
                ).start()
            except Exception as e:
                print(f"[TrayIcon] Activate error: {e}")

    def _cb_standby(self, icon, item) -> None:
        if self._on_standby:
            try:
                threading.Thread(
                    target=self._on_standby,
                    daemon=True,
                    name="AfroTrayStandby",
                ).start()
            except Exception as e:
                print(f"[TrayIcon] Standby error: {e}")

    def _cb_deep_focus(self, icon, item) -> None:
        if self._on_deep_focus:
            try:
                threading.Thread(
                    target=self._on_deep_focus,
                    daemon=True,
                    name="AfroTrayFocus",
                ).start()
            except Exception as e:
                print(f"[TrayIcon] Deep focus trigger error: {e}")

    def _cb_restart(self, icon, item) -> None:
        print("[TrayIcon] Restart requested via tray.")
        icon.stop()
        try:
            import time
            time.sleep(0.3)
            os.execv(sys.executable, ["python"] + sys.argv)
        except Exception as e:
            print(f"[TrayIcon] Restart failed: {e}")

    def _cb_startup_toggle(self, icon, item) -> None:
        current = _startup_enabled()
        _set_startup(not current)
        # Rebuild menu so checkbox reflects new state
        if self._icon is not None:
            self._icon.menu = self._build_menu()

    def _cb_exit(self, icon, item) -> None:
        print("[TrayIcon] Exit requested via tray.")
        icon.stop()
        if self._on_exit:
            try:
                self._on_exit()
            except Exception:
                pass
        os._exit(0)

    # ── State update ──────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Thread-safe state update. state: 'ACTIVE' | 'IDLE'"""
        if state not in ("ACTIVE", "IDLE"):
            return
        with self._lock:
            if self._state == state:
                return
            self._state = state

        if self._icon is not None:
            try:
                self._icon.icon  = self._icon_for_state()
                self._icon.title = f"Afro — {state}"
            except Exception:
                pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open Dashboard",      self._cb_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Activate Afro",       self._cb_activate),
            pystray.MenuItem("Standby",             self._cb_standby),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Deep Focus",          self._cb_deep_focus),
            pystray.MenuItem("Restart Agent",       self._cb_restart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._cb_startup_toggle,
                checked=lambda item: _startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",                self._cb_exit),
        )

    def _run(self) -> None:
        try:
            self._icon = pystray.Icon(
                name  = "Afro",
                icon  = self._icon_for_state(),
                title = f"Afro — {self._state}",
                menu  = self._build_menu(),
            )
            self._icon.run()
        except Exception as e:
            print(f"[TrayIcon] Fatal error in tray thread: {e}")

    def start(self) -> None:
        """Launch tray in a daemon background thread (non-blocking)."""
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="AfroTrayIcon",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: TrayIconManager | None = None


def init_tray(
    on_activate=None,
    on_standby=None,
    on_deep_focus=None,
    on_exit=None,
) -> TrayIconManager:
    global _manager
    _manager = TrayIconManager(
        on_activate=on_activate,
        on_standby=on_standby,
        on_deep_focus=on_deep_focus,
        on_exit=on_exit,
    )
    _manager.start()
    return _manager


def set_tray_state(state: str) -> None:
    """Thread-safe state update callable from anywhere."""
    if _manager is not None:
        _manager.set_state(state)


# Legacy shim — kept for compatibility with core/system_tray.py callers
def start_tray() -> None:
    init_tray()
