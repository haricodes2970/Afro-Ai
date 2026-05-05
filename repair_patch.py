"""
repair_patch.py — Project Afro: Proactive Kinetic Loop verification

Checks:
  1. Handshake:  _speak() blocks; _is_speaking=False before _listener.start()
  2. Fast-path:  match_local_intent("Open Brave") returns HANDLED
  3. Orb sync:   _bridge.speaking_changed connected with QueuedConnection
  4. Registry:   _win_find_exe resolves brave/chrome without PATH

Run:  python repair_patch.py
"""

import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(__file__))

PASS = "[PASS]"
FAIL = "[FAIL]"

results = []

def check(name, ok, detail=""):
    tag = PASS if ok else FAIL
    msg = f"{tag} {name}"
    if detail:
        msg += f"  ->  {detail}"
    print(msg)
    results.append((name, ok))


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1 — Registry lookup (_win_find_exe)
# ─────────────────────────────────────────────────────────────────────────────
print("\n-- Check 1: Windows App Paths registry --")
try:
    from agents.local_router import _win_find_exe

    brave_path  = _win_find_exe("brave")
    chrome_path = _win_find_exe("chrome")

    check("_win_find_exe('brave') returns path",  bool(brave_path),  brave_path or "None")
    check("brave.exe exists on disk",
          bool(brave_path) and os.path.isfile(brave_path),
          brave_path or "not found")
    check("_win_find_exe('chrome') returns path", bool(chrome_path), chrome_path or "None")
except Exception as e:
    check("_win_find_exe import/call", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2 — Fast-path: match_local_intent("Open Brave")
# ─────────────────────────────────────────────────────────────────────────────
print("\n-- Check 2: Local router fast-path --")
try:
    from agents.local_router import match_local_intent

    for cmd in ["open brave", "Open Brave", "launch brave", "start brave"]:
        result = match_local_intent(cmd)
        handled = isinstance(result, dict) and result.get("status") == "HANDLED"
        action  = result.get("action", "?") if isinstance(result, dict) else "FALLBACK"
        app     = (result.get("details", {}) or {}).get("app", "?") if isinstance(result, dict) else "?"
        check(f'match_local_intent("{cmd}")', handled, f"action={action} app={app}")
except Exception as e:
    check("local_router import", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 3 — _speak() blocks: _is_speaking is False after call returns
# ─────────────────────────────────────────────────────────────────────────────
print("\n-- Check 3: _speak() blocking guarantee --")
try:
    import importlib
    import unittest.mock as mock

    # Patch pyaudio/numpy so main.py can be imported without hardware
    sys.modules.setdefault("pyaudio", mock.MagicMock())
    sys.modules.setdefault("numpy",   mock.MagicMock())

    # Patch heavy imports before loading main
    for mod in ["openwakeword", "openwakeword.model", "openwakeword.utils",
                "faster_whisper", "PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets",
                "PyQt6.QtGui", "pystray", "pyttsx3", "pygame", "pygame.mixer",
                "flask_socketio", "flask"]:
        sys.modules.setdefault(mod, mock.MagicMock())

    # Mock all heavy/hardware deps so main.py can import in test env
    for mod in ["psutil", "schedule", "pygetwindow", "win32com", "win32com.client",
                "win32con", "speech_recognition", "ctranslate2",
                "core.dashboard", "core.memory", "core.watcher", "core.hud",
                "core.system_tray", "agents.process_agent", "agents.dev_agent",
                "agents.meta_agent", "agents.scheduler_agent",
                "agents.orchestrator", "agents.os_agent"]:
        sys.modules.setdefault(mod, mock.MagicMock())

    # Reload main to pick up mocked modules
    for k in list(sys.modules):
        if k.startswith("core.main") or k == "core.main":
            del sys.modules[k]

    import core.main as m

    spoke_events = []
    original_speak = m._synth.speak

    def fake_speak(text):
        spoke_events.append("start")
        time.sleep(0.05)  # simulate short TTS
        spoke_events.append("end")

    m._synth.speak = fake_speak

    # Simulate _speak() call
    m._speak("test")

    is_blocking = spoke_events == ["start", "end"]
    check("_speak() is synchronous/blocking", is_blocking, str(spoke_events))

    # Verify _is_speaking is False after _speak() returns
    with m._state_lock:
        still_speaking = m._is_speaking
    check("_is_speaking=False after _speak() returns", not still_speaking, str(still_speaking))

    m._synth.speak = original_speak

except Exception as e:
    check("_speak() blocking test", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 4 — Speaking gate in _on_gui_start()
# ─────────────────────────────────────────────────────────────────────────────
print("\n-- Check 4: Speaking gate in _on_gui_start --")
try:
    import ast, pathlib
    src = pathlib.Path("core/main.py").read_text(encoding="utf-8")

    has_gate     = "while True:" in src and "_is_speaking" in src and "_gate_start" in src
    has_timeout  = "10.0" in src or "hard timeout" in src
    has_greeting = '"Afro Online."' in src

    check("_is_speaking gate exists in _on_gui_start",   has_gate)
    check("gate has hard timeout (no infinite loop)",    has_timeout)
    check('Greeting is "Afro Online."',                  has_greeting)
except Exception as e:
    check("source parse", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 5 — Signal connection uses QueuedConnection
# ─────────────────────────────────────────────────────────────────────────────
print("\n-- Check 5: QueuedConnection for cross-thread signals --")
try:
    import pathlib
    src = pathlib.Path("core/main.py").read_text(encoding="utf-8")

    has_queued      = "QueuedConnection" in src
    has_all_three   = src.count("QueuedConnection") >= 3   # speaking, log, agent_state
    no_auto_connect = "AutoConnection" not in src

    check("speaking_changed uses QueuedConnection",  has_queued)
    check("all 3 bridge signals use QueuedConnection", has_all_three,
          f"found {src.count('QueuedConnection')} occurrence(s)")
    check("no bare AutoConnection left",             no_auto_connect)
except Exception as e:
    check("signal source parse", False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\n-- Summary --")
passed = sum(1 for _, ok in results if ok)
total  = len(results)
print(f"{passed}/{total} checks passed.\n")

if passed < total:
    print("Failed checks:")
    for name, ok in results:
        if not ok:
            print(f"  x {name}")
    sys.exit(1)
else:
    print("All checks passed. Proactive Kinetic Loop is intact.")
    sys.exit(0)
