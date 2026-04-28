import ctypes
import os
import socket
import sys
import threading
import time
from typing import Callable

_PING_HOST    = "1.1.1.1"
_PING_PORT    = 53          # DNS — always open, minimal overhead
_PING_TIMEOUT = 3           # seconds
_INTERVAL_S   = 30          # watchdog cadence


class ResilienceMonitor:
    """
    Continuous health monitor.

    Properties (thread-safe):
      is_online       bool    — network reachability
      has_admin       bool    — process has admin privileges
      execution_mode  str     — "HYBRID" | "LOCAL_ONLY"
    """

    def __init__(
        self,
        on_network_change: Callable[[bool], None] | None = None,
        on_warning:        Callable[[str],  None] | None = None,
    ):
        self._lock           = threading.Lock()
        self._is_online      = True
        self._has_admin      = False
        self._execution_mode = "HYBRID"      # "HYBRID" | "LOCAL_ONLY"

        self._on_network_change = on_network_change
        self._on_warning        = on_warning

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_online(self) -> bool:
        with self._lock:
            return self._is_online

    @property
    def has_admin(self) -> bool:
        with self._lock:
            return self._has_admin

    @property
    def execution_mode(self) -> str:
        with self._lock:
            return self._execution_mode

    # ── Internal checks ───────────────────────────────────────────────────────

    def _check_network(self) -> bool:
        try:
            sock = socket.create_connection(
                (_PING_HOST, _PING_PORT), timeout=_PING_TIMEOUT
            )
            sock.close()
            return True
        except OSError:
            return False

    def _check_admin(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _emit_network_change(self, online: bool) -> None:
        if self._on_network_change:
            try:
                self._on_network_change(online)
            except Exception as e:
                print(f"[ResilienceMonitor] on_network_change error: {e}")

    def _emit_warning(self, msg: str) -> None:
        if self._on_warning:
            try:
                self._on_warning(msg)
            except Exception as e:
                print(f"[ResilienceMonitor] on_warning error: {e}")

    # ── Network watchdog loop (daemon thread) ─────────────────────────────────

    def _network_loop(self) -> None:
        while not self._stop_event.is_set():
            online = self._check_network()
            with self._lock:
                changed              = online != self._is_online
                self._is_online      = online
                self._execution_mode = "HYBRID" if online else "LOCAL_ONLY"

            if changed:
                mode = "HYBRID" if online else "LOCAL_ONLY"
                print(f"[ResilienceMonitor] Network {'ONLINE' if online else 'OFFLINE'} — execution_mode: {mode}")
                self._emit_network_change(online)

            self._stop_event.wait(timeout=_INTERVAL_S)

    # ── App path validation ───────────────────────────────────────────────────

    def validate_app_path(self, app_path: str) -> bool:
        """
        Verify app_path exists on disk.
        If stale: triggers background AppIndexer rebuild and returns False.
        Caller should fall back to alias table on False.
        """
        if not app_path:
            return False
        if os.path.exists(app_path):
            return True

        print(f"[ResilienceMonitor] Stale app path: {app_path!r} — triggering index rebuild.")
        try:
            from agents.app_indexer import start_background_indexing
            start_background_indexing()
        except Exception as e:
            print(f"[ResilienceMonitor] AppIndexer rebuild error: {e}")

        return False

    # ── Startup sequence ──────────────────────────────────────────────────────

    def startup_checks(self) -> None:
        # Admin privileges
        admin = self._check_admin()
        with self._lock:
            self._has_admin = admin

        if not admin:
            msg = "Limited OS Access: Some global hotkeys may fail."
            print(f"[ResilienceMonitor] {msg}")
            self._emit_warning(msg)

        # Initial network probe
        online = self._check_network()
        with self._lock:
            self._is_online      = online
            self._execution_mode = "HYBRID" if online else "LOCAL_ONLY"

        if not online:
            print("[ResilienceMonitor] No network on startup — execution_mode: LOCAL_ONLY")
            self._emit_network_change(False)
        else:
            print("[ResilienceMonitor] Network online — execution_mode: HYBRID")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self.startup_checks()
        self._thread = threading.Thread(
            target=self._network_loop,
            daemon=True,
            name="AfroResilienceMonitor",
        )
        self._thread.start()
        print("[ResilienceMonitor] Watchdog started (30s network poll).")

    def stop(self) -> None:
        self._stop_event.set()


# ── Module-level singleton ────────────────────────────────────────────────────

_monitor: ResilienceMonitor | None = None
_init_lock = threading.Lock()


def init_monitor(
    on_network_change: Callable[[bool], None] | None = None,
    on_warning:        Callable[[str],  None] | None = None,
) -> ResilienceMonitor:
    """Create and start the singleton monitor. Safe to call once at startup."""
    global _monitor
    with _init_lock:
        if _monitor is None:
            _monitor = ResilienceMonitor(
                on_network_change=on_network_change,
                on_warning=on_warning,
            )
            _monitor.start()
    return _monitor


def get_monitor() -> ResilienceMonitor:
    """Return the singleton, creating a default (no callbacks) instance if needed."""
    global _monitor
    if _monitor is None:
        with _init_lock:
            if _monitor is None:
                _monitor = ResilienceMonitor()
                _monitor.start()
    return _monitor
