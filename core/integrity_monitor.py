"""
core/integrity_monitor.py

Proactive environmental integrity monitor for Project Afro.

Responsibilities:
  1. APP PATH INTEGRITY  — periodic scan of all known aliases + app_index.json
                           entries; stale paths trigger AppIndexer rebuild.
  2. ADMIN GUARD         — startup check; emits warning when not elevated.
  3. NETWORK / LOCAL_ONLY — delegates to ResilienceMonitor; exposes
                           execution_mode so orchestrator and callers get a
                           single authoritative answer without a second ping loop.

Emits via callbacks (wired to _bridge signals in main.py):
  on_log(msg: str)             — CockpitUI terminal line
  on_admin_warning(msg: str)   — one-time startup warning
  on_network_change(bool)      — forwarded from ResilienceMonitor
  on_app_stale(name: str)      — stale app detected; rebuild scheduled
"""

import ctypes
import json
import os
import sys
import threading
import time
from typing import Callable

# ── Tunables ──────────────────────────────────────────────────────────────────

_INTEGRITY_INTERVAL_S = 300   # app-path scan cadence (5 minutes)
_ADMIN_MSG            = "Limited Control: Some system-level apps may not focus."

# ── IntegrityMonitor ──────────────────────────────────────────────────────────

class IntegrityMonitor:
    """
    Background monitor that validates app paths, guards admin state,
    and surfaces network mode — all without blocking the UI thread.
    """

    def __init__(
        self,
        on_log:            Callable[[str],  None] | None = None,
        on_admin_warning:  Callable[[str],  None] | None = None,
        on_network_change: Callable[[bool], None] | None = None,
        on_app_stale:      Callable[[str],  None] | None = None,
    ):
        self._lock             = threading.Lock()
        self._has_admin        = False
        self._stop_event       = threading.Event()
        self._thread: threading.Thread | None = None

        self._on_log            = on_log
        self._on_admin_warning  = on_admin_warning
        self._on_network_change = on_network_change
        self._on_app_stale      = on_app_stale

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def has_admin(self) -> bool:
        with self._lock:
            return self._has_admin

    @property
    def execution_mode(self) -> str:
        """Delegates to ResilienceMonitor — single source of truth."""
        try:
            from core.resilience_monitor import get_monitor
            return get_monitor().execution_mode
        except Exception:
            return "HYBRID"

    @property
    def is_online(self) -> bool:
        try:
            from core.resilience_monitor import get_monitor
            return get_monitor().is_online
        except Exception:
            return True

    # ── Internal emitters ─────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        print(f"[IntegrityMonitor] {msg}")
        if self._on_log:
            try:
                self._on_log(msg)
            except Exception:
                pass

    def _emit_admin_warning(self, msg: str) -> None:
        if self._on_admin_warning:
            try:
                self._on_admin_warning(msg)
            except Exception:
                pass

    def _emit_network_change(self, online: bool) -> None:
        if self._on_network_change:
            try:
                self._on_network_change(online)
            except Exception:
                pass

    def _emit_app_stale(self, name: str) -> None:
        if self._on_app_stale:
            try:
                self._on_app_stale(name)
            except Exception:
                pass

    # ── Admin check ───────────────────────────────────────────────────────────

    def _check_admin(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    # ── App path integrity scan ───────────────────────────────────────────────

    def _scan_registry_aliases(self) -> list[str]:
        """
        Check every known app alias via _win_find_exe().
        If registry returns a path but the file is gone → stale.
        Returns list of stale alias names.
        """
        stale: list[str] = []
        try:
            from agents.local_router import _APP_TARGETS, _win_find_exe
        except Exception as e:
            self._log(f"Cannot import local_router for alias scan: {e}")
            return stale

        for key, alias_target in _APP_TARGETS.items():
            try:
                reg_path = _win_find_exe(alias_target)
                if reg_path and not os.path.isfile(reg_path):
                    self._log(f"Stale registry path [{key}]: {reg_path!r}")
                    stale.append(key)
            except Exception as e:
                self._log(f"Alias scan error [{key}]: {e}")

        return stale

    def _scan_app_index(self) -> list[str]:
        """
        Check every entry in config/app_index.json.
        Collects entries where the target .exe no longer exists.
        Returns list of stale display names.
        """
        stale: list[str] = []
        index_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "config", "app_index.json")
        )
        if not os.path.isfile(index_path):
            return stale

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            apps: dict[str, str] = data.get("apps", {})
        except Exception as e:
            self._log(f"app_index.json read error: {e}")
            return stale

        for name, path in apps.items():
            if path and not os.path.isfile(path):
                self._log(f"Stale index entry [{name}]: {path!r}")
                stale.append(name)

        return stale

    def _run_integrity_scan(self) -> None:
        """Full scan: registry aliases + app index. Rebuilds index if stale."""
        self._log("Running app path integrity scan...")

        stale_aliases = self._scan_registry_aliases()
        stale_indexed = self._scan_app_index()
        all_stale     = stale_aliases + stale_indexed

        if all_stale:
            self._log(
                f"Integrity scan found {len(all_stale)} stale path(s) — "
                f"triggering AppIndexer rebuild."
            )
            for name in all_stale:
                self._emit_app_stale(name)
            try:
                from agents.app_indexer import start_background_indexing
                start_background_indexing()
            except Exception as e:
                self._log(f"AppIndexer rebuild trigger failed: {e}")
        else:
            self._log(
                f"Integrity scan clean — registry aliases OK, "
                f"app index OK."
            )

    # ── Network change bridge ─────────────────────────────────────────────────

    def _attach_network_callback(self) -> None:
        """
        Wire self._emit_network_change into ResilienceMonitor's callback slot
        so we forward network events without running a second ping loop.
        """
        try:
            from core.resilience_monitor import get_monitor
            monitor = get_monitor()
            # Wrap existing callback to chain ours alongside it
            existing = monitor._on_network_change

            def _chained(online: bool) -> None:
                if existing:
                    try:
                        existing(online)
                    except Exception:
                        pass
                self._emit_network_change(online)
                if not online:
                    self._log("Network offline — execution_mode: LOCAL_ONLY")
                else:
                    self._log("Network restored — execution_mode: HYBRID")

            monitor._on_network_change = _chained
        except Exception as e:
            self._log(f"Could not attach network callback: {e}")

    # ── Startup checks (blocking, called before background thread) ─────────────

    def startup_checks(self) -> None:
        # Admin guard
        admin = self._check_admin()
        with self._lock:
            self._has_admin = admin

        if not admin:
            self._log(_ADMIN_MSG)
            self._emit_admin_warning(_ADMIN_MSG)
        else:
            self._log("Admin privileges confirmed.")

        # Network state (read from ResilienceMonitor — it runs first)
        online = self.is_online
        mode   = self.execution_mode
        self._log(f"Network: {'ONLINE' if online else 'OFFLINE'} — execution_mode: {mode}")
        if not online:
            self._emit_network_change(False)

        # Initial app integrity scan (fast — just checks os.path.isfile)
        self._run_integrity_scan()

    # ── Background scan loop ──────────────────────────────────────────────────

    def _scan_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_INTEGRITY_INTERVAL_S)
            if not self._stop_event.is_set():
                self._run_integrity_scan()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Startup sequence:
          1. Attach network callback to ResilienceMonitor (no duplicate ping).
          2. Run startup checks (admin + network state + initial path scan).
          3. Launch background scan loop (5-minute cadence).
        """
        self._attach_network_callback()
        self.startup_checks()

        self._thread = threading.Thread(
            target=self._scan_loop,
            daemon=True,
            name="AfroIntegrityMonitor",
        )
        self._thread.start()
        self._log("IntegrityMonitor started (5-min scan cadence).")

    def stop(self) -> None:
        self._stop_event.set()

    def force_scan(self) -> None:
        """Trigger an immediate out-of-cycle integrity scan (callable from UI)."""
        threading.Thread(
            target=self._run_integrity_scan,
            daemon=True,
            name="AfroIntegrityScan",
        ).start()


# ── Module-level singleton ────────────────────────────────────────────────────

_monitor: IntegrityMonitor | None = None
_init_lock = threading.Lock()


def init_integrity_monitor(
    on_log:            Callable[[str],  None] | None = None,
    on_admin_warning:  Callable[[str],  None] | None = None,
    on_network_change: Callable[[bool], None] | None = None,
    on_app_stale:      Callable[[str],  None] | None = None,
) -> IntegrityMonitor:
    """Create, wire, and start the singleton. Call once at startup."""
    global _monitor
    with _init_lock:
        if _monitor is None:
            _monitor = IntegrityMonitor(
                on_log=on_log,
                on_admin_warning=on_admin_warning,
                on_network_change=on_network_change,
                on_app_stale=on_app_stale,
            )
            _monitor.start()
    return _monitor


def get_integrity_monitor() -> IntegrityMonitor:
    """Return singleton, creating default (no callbacks) instance if needed."""
    global _monitor
    if _monitor is None:
        with _init_lock:
            if _monitor is None:
                _monitor = IntegrityMonitor()
                _monitor.start()
    return _monitor
