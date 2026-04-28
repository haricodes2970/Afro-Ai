import os
import re
import sys
import subprocess

_HOME = os.path.expanduser("~")

# ── Compiled patterns ─────────────────────────────────────────────────────────
_RE_OPEN   = re.compile(r"^open\s+(.+)$",           re.IGNORECASE)
_RE_FOLDER = re.compile(r"^create\s+folder\s+(.+)$", re.IGNORECASE)
_RE_EXIT   = re.compile(r"^(stop|goodbye|exit|quit|bye)$", re.IGNORECASE)

# Characters that must not appear in folder names or app names passed to shell
_UNSAFE = re.compile(r"[;&|`$<>\"\'\\]")


def _sanitize(value: str) -> str:
    """Strip whitespace and reject shell-injection characters."""
    value = value.strip()
    if _UNSAFE.search(value):
        raise ValueError(f"Unsafe characters in input: {value!r}")
    return value


def _handle_open(app_name: str) -> bool:
    try:
        app_name = _sanitize(app_name)
        if not app_name:
            return False
        print(f"Local execution: open {app_name!r}")
        subprocess.Popen(
            [app_name],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except ValueError as e:
        print(f"[LocalRouter] Rejected unsafe app name: {e}")
        return False
    except FileNotFoundError:
        # app not on PATH — let API router handle it
        print(f"[LocalRouter] '{app_name}' not found on PATH; falling back.")
        return False
    except Exception as e:
        print(f"[LocalRouter] open error: {e}")
        return False


def _handle_create_folder(folder_name: str) -> bool:
    try:
        folder_name = _sanitize(folder_name)
        if not folder_name:
            return False

        # Resolve relative to home; block absolute paths injected by user
        if os.path.isabs(folder_name):
            print("[LocalRouter] Absolute paths not accepted; using home-relative name.")
            folder_name = os.path.basename(folder_name)

        path = os.path.normpath(os.path.join(_HOME, folder_name))

        # Confirm the resolved path is still inside home
        if not path.startswith(os.path.normpath(_HOME)):
            print(f"[LocalRouter] Path escapes home directory: {path!r}")
            return False

        os.makedirs(path, exist_ok=True)
        print(f"Local execution: create folder {path!r}")
        return True
    except ValueError as e:
        print(f"[LocalRouter] Rejected unsafe folder name: {e}")
        return False
    except OSError as e:
        print(f"[LocalRouter] Folder creation error: {e}")
        return False
    except Exception as e:
        print(f"[LocalRouter] create_folder error: {e}")
        return False


def _handle_exit() -> bool:
    print("Shutting down Afro")
    sys.exit(0)


def match_local_intent(command_text: str) -> bool:
    """
    Attempt to handle command_text locally without any API call.

    Returns True  — command was handled locally.
    Returns False — no local match; caller should forward to API router.
    """
    if not command_text or not isinstance(command_text, str):
        return False

    text = command_text.strip()

    m = _RE_EXIT.match(text)
    if m:
        return _handle_exit()

    m = _RE_OPEN.match(text)
    if m:
        return _handle_open(m.group(1))

    m = _RE_FOLDER.match(text)
    if m:
        return _handle_create_folder(m.group(1))

    return False
