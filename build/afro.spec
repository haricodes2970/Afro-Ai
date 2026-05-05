# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Project Afro
# Build:  pyinstaller build/afro.spec
# Output: dist/Afro.exe (single-file, no console)

import os
import sys
from pathlib import Path

block_cipher = None

# Project root is one level above the build/ directory
ROOT = Path(SPECPATH).parent

# ── Collected data files ──────────────────────────────────────────────────────

datas = [
    # config JSON (knowledge_base, app_index cache, etc.)
    (str(ROOT / "config"),    "config"),
    # Flask templates
    (str(ROOT / "templates"), "templates"),
    # Static assets (CSS, JS)
    (str(ROOT / "static"),    "static"),
    # Bundled icon (used by tray at runtime via sys._MEIPASS)
    (str(ROOT / "assets"),    "assets"),
]

# Include openwakeword model directory if it exists on this build machine
try:
    import openwakeword as _oww
    _oww_models = Path(_oww.__file__).parent / "resources" / "models"
    if _oww_models.is_dir():
        datas.append((str(_oww_models), "openwakeword/resources/models"))
except Exception:
    pass

# ── Analysis ──────────────────────────────────────────────────────────────────

a = Analysis(
    [str(ROOT / "core" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # UI
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        # Tray
        "pystray",
        "pystray._win32",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        # Audio
        "pyaudio",
        "numpy",
        "soundfile",
        # Wake word
        "openwakeword",
        "openwakeword.model",
        "openwakeword.utils",
        "onnxruntime",
        # Transcription
        "faster_whisper",
        "ctranslate2",
        # Web / dashboard
        "flask",
        "flask_socketio",
        "engineio",
        "socketio",
        "eventlet",
        "eventlet.hubs.epolls",
        "eventlet.hubs.kqueue",
        "eventlet.hubs.selects",
        "dns",
        "dns.resolver",
        # TTS
        "pyttsx3",
        "pyttsx3.drivers",
        "pyttsx3.drivers.sapi5",
        "pygame",
        "pygame.mixer",
        # LLM / API
        "groq",
        "google.generativeai",
        "anthropic",
        "requests",
        # OS / automation
        "pyautogui",
        "psutil",
        "winreg",
        "ctypes",
        "ctypes.windll",
        "win32com",
        "win32com.client",
        "win32con",
        "speech_recognition",
        # Stdlib extensions
        "sqlite3",
        "difflib",
        "schedule",
        "webbrowser",
        "subprocess",
        # Project modules (ensure PyInstaller finds them)
        "core.main",
        "core.dashboard",
        "core.intent_router",
        "core.memory",
        "core.tray_icon",
        "core.cockpit_ui",
        "core.resilience_monitor",
        "core.watcher",
        "core.hud",
        "core.evolution_engine",
        "core.ide_controller",
        "core.safety",
        "agents.orchestrator",
        "agents.local_router",
        "agents.app_indexer",
        "agents.process_agent",
        "agents.dev_agent",
        "agents.file_agent",
        "agents.meta_agent",
        "agents.os_agent",
        "agents.scheduler_agent",
        "agents.clipboard_agent",
        "voice.listener",
        "voice.transcribe",
        "voice.synthesizer",
        "communication.web_search",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "test",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Single-file executable ────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Afro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python*.dll"],
    runtime_tmpdir=None,
    console=False,                  # windowed — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "afro.ico"),
    version_file=None,
)
