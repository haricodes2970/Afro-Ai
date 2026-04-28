import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_EXT_BUCKETS: dict[str, set[str]] = {
    "images":     {"jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "ico", "tiff", "raw"},
    "videos":     {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v", "3gp"},
    "docs":       {"pdf", "doc", "docx", "txt", "odt", "rtf", "pptx", "ppt", "xlsx", "xls", "csv", "md"},
    "audio":      {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus"},
    "archives":   {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"},
    "code":       {"py", "js", "ts", "html", "css", "java", "cpp", "c", "h", "cs", "go", "rs", "php", "rb", "sh", "bat", "ps1"},
    "installers": {"exe", "msi", "dmg", "pkg", "deb", "rpm", "appimage"},
}

_EXT_TO_BUCKET: dict[str, str] = {
    ext: bucket
    for bucket, exts in _EXT_BUCKETS.items()
    for ext in exts
}


def _confirm(description: str) -> bool:
    try:
        from core.safety import confirm_action
        return confirm_action(description)
    except Exception:
        answer = input(f"Confirm: {description}? [y/N] ").strip().lower()
        return answer in ("y", "yes")


class OSAgent:

    # ── A) create_folder ────────────────────────────────────────────
    def create_folder(self, path: str) -> bool:
        try:
            os.makedirs(path, exist_ok=True)
            print(f"[OSAgent] Created folder: {path}")
            return True
        except OSError as e:
            print(f"[OSAgent] create_folder failed: {e}", file=sys.stderr)
            return False

    # ── B) delete_item ──────────────────────────────────────────────
    def delete_item(self, path: str) -> bool:
        path = os.path.expandvars(os.path.expanduser(path))
        if not os.path.exists(path):
            print(f"[OSAgent] Path not found: {path}")
            return False

        if not _confirm(f"Delete {'folder' if os.path.isdir(path) else 'file'}: {path}"):
            print("[OSAgent] Deletion cancelled.")
            return False

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            print(f"[OSAgent] Deleted: {path}")
            return True
        except OSError as e:
            print(f"[OSAgent] delete_item failed: {e}", file=sys.stderr)
            return False

    # ── C) sort_directory ───────────────────────────────────────────
    def sort_directory(self, path: str, criteria: str = "") -> dict[str, int]:
        path = os.path.expandvars(os.path.expanduser(path))
        if not os.path.isdir(path):
            print(f"[OSAgent] Not a directory: {path}")
            return {}

        criteria = criteria.lower().strip().lstrip(".")
        moved: dict[str, int] = {}

        for entry in Path(path).iterdir():
            if not entry.is_file():
                continue

            ext = entry.suffix.lstrip(".").lower()

            # If criteria is a specific extension, only move matching files
            if criteria and criteria not in _EXT_BUCKETS:
                if ext != criteria:
                    continue
                bucket = _EXT_TO_BUCKET.get(ext, "misc")
            else:
                # criteria is a bucket name or empty — sort everything
                target_bucket = criteria if criteria in _EXT_BUCKETS else None
                bucket = _EXT_TO_BUCKET.get(ext, "misc")
                if target_bucket and bucket != target_bucket:
                    continue

            dest_dir = os.path.join(path, bucket)
            os.makedirs(dest_dir, exist_ok=True)

            dest = os.path.join(dest_dir, entry.name)
            # Avoid collision
            if os.path.exists(dest):
                stem = entry.stem
                suffix = entry.suffix
                counter = 1
                while os.path.exists(dest):
                    dest = os.path.join(dest_dir, f"{stem}_{counter}{suffix}")
                    counter += 1

            shutil.move(str(entry), dest)
            moved[bucket] = moved.get(bucket, 0) + 1
            print(f"[OSAgent] Moved {entry.name} → {bucket}/")

        total = sum(moved.values())
        print(f"[OSAgent] sort_directory complete: {total} file(s) moved → {moved}")
        return moved

    # ── D) install_app ──────────────────────────────────────────────
    def install_app(self, app_name: str) -> bool:
        print(f"[OSAgent] Installing: {app_name}")

        # winget (Windows Package Manager)
        try:
            result = subprocess.run(
                ["winget", "install", "--id", app_name, "-e", "--accept-package-agreements",
                 "--accept-source-agreements"],
                timeout=300,
                capture_output=False,
            )
            if result.returncode == 0:
                print(f"[OSAgent] winget install succeeded: {app_name}")
                return True
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            print(f"[OSAgent] winget timed out for: {app_name}", file=sys.stderr)
            return False

        # Fallback: chocolatey
        try:
            result = subprocess.run(
                ["choco", "install", app_name, "-y"],
                timeout=300,
                capture_output=False,
            )
            if result.returncode == 0:
                print(f"[OSAgent] choco install succeeded: {app_name}")
                return True
        except FileNotFoundError:
            print(f"[OSAgent] Neither winget nor choco found. Cannot install {app_name}.",
                  file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"[OSAgent] choco timed out for: {app_name}", file=sys.stderr)

        return False

    # ── E) open_vscode ──────────────────────────────────────────────
    def open_vscode(self, filepath: str = "") -> bool:
        try:
            args = ["code"]
            if filepath:
                args.append(os.path.expandvars(os.path.expanduser(filepath)))
            subprocess.Popen(args, shell=False)
            print(f"[OSAgent] VS Code opened{': ' + filepath if filepath else ''}.")
            return True
        except FileNotFoundError:
            print("[OSAgent] 'code' command not found. Is VS Code in PATH?", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[OSAgent] open_vscode failed: {e}", file=sys.stderr)
            return False

    # ── F) focus_editor ─────────────────────────────────────────────
    def focus_editor(self) -> bool:
        try:
            import pyautogui
            import time
            import pygetwindow as gw

            wins = [w for w in gw.getAllWindows() if "visual studio code" in w.title.lower()]
            if wins:
                wins[0].activate()
                time.sleep(0.4)
                print("[OSAgent] VS Code focused.")
                return True

            print("[OSAgent] VS Code window not found.")
            return False
        except Exception as e:
            print(f"[OSAgent] focus_editor failed: {e}", file=sys.stderr)
            return False

    # ── G) type_code ────────────────────────────────────────────────
    def type_code(self, text: str) -> bool:
        try:
            import pyautogui
            import time

            pyautogui.PAUSE = 0.02
            pyautogui.typewrite(text, interval=0.01)
            print(f"[OSAgent] Typed {len(text)} chars into editor.")
            return True
        except Exception as e:
            print(f"[OSAgent] type_code failed: {e}", file=sys.stderr)
            return False
