import os
import json
import time
import difflib
import threading
import subprocess

_INDEX_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "config", "app_index.json")
)
_CACHE_TTL  = 86400   # 24 hours

_index_lock = threading.Lock()
_index: dict[str, str] = {}   # lowered display name → executable path

_START_MENU_DIRS = [
    os.path.join(
        os.environ.get("ProgramData", r"C:\ProgramData"),
        "Microsoft", "Windows", "Start Menu", "Programs",
    ),
    os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft", "Windows", "Start Menu", "Programs",
    ),
]

# ── LNK scanning ──────────────────────────────────────────────────────────────

def _collect_lnk_files() -> list[str]:
    found = []
    for base in _START_MENU_DIRS:
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for f in files:
                if f.lower().endswith(".lnk"):
                    found.append(os.path.join(root, f))
    return found


def _resolve_lnk_batch(lnk_paths: list[str]) -> dict[str, str]:
    """Batch-resolve .lnk → target via a single PowerShell process."""
    if not lnk_paths:
        return {}

    lines = ["$ws = New-Object -ComObject WScript.Shell"]
    for path in lnk_paths:
        esc_path = path.replace("'", "''")
        name     = os.path.splitext(os.path.basename(path))[0].replace("'", "''")
        lines.append(
            f"try {{ $sc = $ws.CreateShortcut('{esc_path}'); "
            f"Write-Output ('{name}|||' + $sc.TargetPath) }} catch {{ }}"
        )

    script = "\n".join(lines)

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        mapping: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if "|||" not in line:
                continue
            parts = line.split("|||", 1)
            name, target = parts[0].strip().lower(), parts[1].strip()
            if name and target and os.path.isfile(target):
                mapping[name] = target
        return mapping
    except Exception as e:
        print(f"[AppIndexer] LNK batch resolve failed: {e}")
        return {}

# ── Index build / persistence ─────────────────────────────────────────────────

def _build_index() -> dict[str, str]:
    lnk_files = _collect_lnk_files()
    print(f"[AppIndexer] Found {len(lnk_files)} .lnk files — resolving targets...")
    return _resolve_lnk_batch(lnk_files)


def _load_cached() -> dict[str, str] | None:
    if not os.path.isfile(_INDEX_PATH):
        return None
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > _CACHE_TTL:
            return None
        return data.get("apps", {})
    except Exception:
        return None


def _save_index(apps: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(_INDEX_PATH), exist_ok=True)
    with open(_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump({"timestamp": time.time(), "apps": apps}, f, indent=2)

# ── Public API ────────────────────────────────────────────────────────────────

def ensure_index() -> None:
    """Load cached index or build a fresh one. Thread-safe."""
    global _index
    with _index_lock:
        cached = _load_cached()
        if cached is not None:
            _index = cached
            print(f"[AppIndexer] Loaded {len(_index)} apps from cache.")
            return
        print("[AppIndexer] Building app index...")
        apps = _build_index()
        _index = apps
        _save_index(apps)
        print(f"[AppIndexer] Indexed {len(_index)} apps.")


def get_app_path(name: str) -> str | None:
    """
    Return the executable path for the best matching app name.
    Returns None if no confident match is found or index is empty.
    """
    with _index_lock:
        if not _index:
            return None

        needle = name.strip().lower()

        if needle in _index:
            return _index[needle]

        # Prefix / contains
        for key, path in _index.items():
            if key.startswith(needle) or needle in key:
                return path

        # Fuzzy
        matches = difflib.get_close_matches(needle, list(_index.keys()), n=1, cutoff=0.65)
        if matches:
            return _index[matches[0]]

        return None


def start_background_indexing() -> None:
    """Build / refresh the app index in a daemon thread (non-blocking)."""
    threading.Thread(target=ensure_index, daemon=True, name="AfroAppIndexer").start()
