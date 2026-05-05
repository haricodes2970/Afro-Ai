import os
import re
import sys
import subprocess
import difflib
import shutil

# ── App alias map ─────────────────────────────────────────────────────────────
APP_ALIASES: dict[str, list[str]] = {
    "chrome":    ["chrome", "google chrome"],
    "brave":     ["brave", "braille", "brav", "brave browser"],
    "vscode":    ["code", "vs code", "visual studio code", "vscode"],
    "notepad":   ["notepad"],
    "explorer":  ["file explorer", "explorer"],
    "firefox":   ["firefox", "mozilla firefox", "fire fox"],
    "spotify":   ["spotify"],
    "discord":   ["discord"],
    "terminal":  ["terminal", "cmd", "command prompt", "powershell"],
    "calculator":["calculator", "calc"],
    "paint":     ["paint", "mspaint"],
}

# Canonical executable / startfile target for each alias key
_APP_TARGETS: dict[str, str] = {
    "chrome":    "chrome",
    "brave":     "brave",
    "vscode":    "code",
    "notepad":   "notepad",
    "explorer":  "explorer",
    "firefox":   "firefox",
    "spotify":   "spotify",
    "discord":   "discord",
    "terminal":  "cmd",
    "calculator":"calc",
    "paint":     "mspaint",
}

# Flat list of all known aliases (used for difflib matching)
_ALL_ALIASES: list[str] = [alias for aliases in APP_ALIASES.values() for alias in aliases]

# Reverse map: alias string → canonical key
_ALIAS_TO_KEY: dict[str, str] = {
    alias: key
    for key, aliases in APP_ALIASES.items()
    for alias in aliases
}

# Characters that must not appear in user-supplied paths or app names
_UNSAFE = re.compile(r"[;&|`$<>\"\'\\]")

# ── Compiled patterns ─────────────────────────────────────────────────────────
_RE_OPEN   = re.compile(r"^\s*(open|launch|start)\s+(.+)$",        re.IGNORECASE)
_RE_FOLDER = re.compile(r"^\s*(create|make)\s+(folder|directory)\s+(.+)$", re.IGNORECASE)
_RE_EXIT   = re.compile(r"^\s*(exit|quit|stop|goodbye)\s*$",        re.IGNORECASE)

_HOME = os.path.expanduser("~")

# ── Windows App Paths registry lookup ────────────────────────────────────────

def _win_find_exe(name: str) -> str | None:
    """
    Look up an executable via HKLM/HKCU App Paths registry.
    Returns full path string if found and file exists, else None.
    This finds browsers (brave, chrome, firefox) that are NOT in PATH.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    exe = name if name.lower().endswith(".exe") else f"{name}.exe"
    reg_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, reg_path) as key:
                full_path, _ = winreg.QueryValueEx(key, "")
                full_path = full_path.strip().strip('"')
                if full_path and os.path.isfile(full_path):
                    return full_path
        except (FileNotFoundError, OSError):
            continue

    return None

# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _sanitize(value: str) -> str:
    value = value.strip()
    if _UNSAFE.search(value):
        raise ValueError(f"Unsafe characters in value: {value!r}")
    return value


def _resolve_app(raw_name: str) -> str | None:
    """
    Map a raw app name to a canonical executable target.
    Uses exact alias match first, then difflib fuzzy match.
    Returns None if no confident match found.
    """
    needle = _normalize(raw_name)

    # Exact match in alias table
    if needle in _ALIAS_TO_KEY:
        key = _ALIAS_TO_KEY[needle]
        return _APP_TARGETS[key]

    # Fuzzy match against all known aliases
    matches = difflib.get_close_matches(needle, _ALL_ALIASES, n=1, cutoff=0.72)
    if matches:
        key = _ALIAS_TO_KEY[matches[0]]
        return _APP_TARGETS[key]

    # No confident match — return the sanitized raw name as-is (best effort)
    return needle if needle else None

# ── Handlers ──────────────────────────────────────────────────────────────────

def _handle_open(raw_name: str) -> dict | str:
    try:
        raw_name = _sanitize(raw_name)
        if not raw_name:
            return "FALLBACK"

        # 1. Alias table + difflib (known apps, fast) → may be bare name e.g. "brave"
        normalized_app = _resolve_app(raw_name)

        # 2. Windows App Paths registry — resolves bare names to full .exe paths
        #    Finds browsers, apps NOT in PATH (brave, chrome, firefox, etc.)
        registry_path: str | None = _win_find_exe(normalized_app) if normalized_app else None

        # 3. App indexer (full Start Menu .lnk scan)
        indexed_path: str | None = None
        try:
            from agents.app_indexer import get_app_path
            indexed_path = get_app_path(raw_name)
        except Exception:
            pass

        # Validate indexed path — stale entry triggers background rebuild
        if indexed_path and not os.path.exists(indexed_path):
            print(f"[LocalRouter] Stale index path: {indexed_path!r} — scheduling rebuild.")
            try:
                from agents.app_indexer import start_background_indexing
                start_background_indexing()
            except Exception:
                pass
            indexed_path = None

        # Resolution priority: registry full path > indexed .lnk path > bare alias name
        target = registry_path or indexed_path or normalized_app
        if not target:
            return "FALLBACK"

        print(f"Local execution: open {target!r}")

        launched = False

        # Primary: os.startfile (Windows — handles .exe, .lnk, protocols)
        if sys.platform == "win32":
            try:
                os.startfile(target)
                launched = True
            except (OSError, FileNotFoundError):
                # Primary target failed — try bare alias via shutil.which or PATH
                for fallback in filter(None, [
                    shutil.which(normalized_app) if normalized_app else None,
                    normalized_app,
                ]):
                    if fallback == target:
                        continue
                    try:
                        os.startfile(fallback)
                        launched = True
                        target = fallback
                        break
                    except (OSError, FileNotFoundError):
                        pass

        # Secondary: subprocess.Popen
        if not launched:
            try:
                subprocess.Popen(
                    [target],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                launched = True
            except FileNotFoundError:
                pass

        if not launched:
            print(f"[LocalRouter] '{target}' not found — falling back to API router.")
            return "FALLBACK"

        return {
            "status":  "HANDLED",
            "action":  "open_app",
            "details": {"app": target},
        }

    except ValueError as e:
        print(f"[LocalRouter] Rejected unsafe app name: {e}")
        return "FALLBACK"
    except Exception as e:
        print(f"[LocalRouter] open error: {e}")
        return "FALLBACK"


def _handle_create_folder(raw_name: str) -> dict | str:
    try:
        raw_name = _sanitize(raw_name)
        if not raw_name:
            return "FALLBACK"

        # Reject absolute paths and traversal attempts
        if os.path.isabs(raw_name) or ".." in raw_name:
            print(f"[LocalRouter] Rejected path: {raw_name!r}")
            raw_name = os.path.basename(raw_name)

        path = os.path.normpath(os.path.join(_HOME, raw_name))

        if not path.startswith(os.path.normpath(_HOME)):
            print(f"[LocalRouter] Path escapes home directory: {path!r}")
            return "FALLBACK"

        os.makedirs(path, exist_ok=True)
        print(f"Local execution: create folder {path!r}")

        return {
            "status":  "HANDLED",
            "action":  "create_folder",
            "details": {"path": path},
        }

    except ValueError as e:
        print(f"[LocalRouter] Rejected unsafe folder name: {e}")
        return "FALLBACK"
    except OSError as e:
        print(f"[LocalRouter] Folder creation error: {e}")
        return "FALLBACK"
    except Exception as e:
        print(f"[LocalRouter] create_folder error: {e}")
        return "FALLBACK"


def _handle_exit() -> dict:
    print("Shutting down Afro")
    result: dict = {"status": "HANDLED", "action": "exit", "details": {}}
    sys.exit(0)
    return result  # unreachable — satisfies type checker


# ── Public interface ──────────────────────────────────────────────────────────

def match_local_intent(text: str) -> dict | str:
    """
    Attempt to handle `text` locally without any API call.

    Returns:
        dict  {"status": "HANDLED", "action": "<name>", "details": {...}}
        OR
        str   "FALLBACK"  — caller should forward to LLM router
    """
    if not text or not isinstance(text, str):
        return "FALLBACK"

    normalized = _normalize(text)

    m = _RE_EXIT.match(normalized)
    if m:
        return _handle_exit()

    m = _RE_OPEN.match(normalized)
    if m:
        return _handle_open(m.group(2))

    m = _RE_FOLDER.match(normalized)
    if m:
        return _handle_create_folder(m.group(3))

    return "FALLBACK"
