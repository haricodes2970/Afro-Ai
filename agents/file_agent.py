import os
import re
import shutil
from datetime import datetime, timedelta

EXTENSION_MAP = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv"},
    "Documents": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".txt", ".csv"},
}


def _categorize(ext: str) -> str:
    ext = ext.lower()
    for folder, extensions in EXTENSION_MAP.items():
        if ext in extensions:
            return folder
    return "Others"


class FileAgent:

    def sort(self, target_directory: str) -> None:
        if not os.path.isdir(target_directory):
            print(f"[FileAgent] Directory not found: {target_directory}")
            return

        moved = 0
        for filename in os.listdir(target_directory):
            file_path = os.path.join(target_directory, filename)
            if not os.path.isfile(file_path):
                continue

            _, ext = os.path.splitext(filename)
            folder_name = _categorize(ext)
            dest_dir = os.path.join(target_directory, folder_name)
            os.makedirs(dest_dir, exist_ok=True)

            dest_path = os.path.join(dest_dir, filename)
            shutil.move(file_path, dest_path)
            print(f"[FileAgent] Moved: {filename} → {folder_name}/")
            moved += 1

        print(f"[FileAgent] Sort complete. {moved} file(s) moved.")

    def clean(
        self,
        target_directory: str,
        age_days: int | None = None,
        size_mb: float | None = None,
    ) -> None:
        if not os.path.isdir(target_directory):
            print(f"[FileAgent] Directory not found: {target_directory}")
            return

        candidates = []
        now = datetime.now()
        size_bytes = (size_mb * 1024 * 1024) if size_mb is not None else None

        for filename in os.listdir(target_directory):
            file_path = os.path.join(target_directory, filename)
            if not os.path.isfile(file_path):
                continue

            stat = os.stat(file_path)
            file_age_days = (now - datetime.fromtimestamp(stat.st_mtime)).days
            file_size_mb = stat.st_size / (1024 * 1024)

            age_match = age_days is not None and file_age_days > age_days
            size_match = size_bytes is not None and stat.st_size > size_bytes

            if age_match or size_match:
                candidates.append(
                    f"  {filename} | {file_age_days}d old | {file_size_mb:.2f} MB"
                )

        if candidates:
            print(f"[FileAgent] Candidate files for cleanup in '{target_directory}':")
            for c in candidates:
                print(c)
            print(f"[FileAgent] {len(candidates)} candidate(s) identified. No files deleted.")
        else:
            print("[FileAgent] No files matched the cleanup criteria.")

    def rename(self, target_directory: str, pattern: str | None = None) -> None:
        if not os.path.isdir(target_directory):
            print(f"[FileAgent] Directory not found: {target_directory}")
            return

        prefix = datetime.now().strftime("%Y%m%d")
        renamed = 0

        for filename in os.listdir(target_directory):
            file_path = os.path.join(target_directory, filename)
            if not os.path.isfile(file_path):
                continue

            if pattern:
                if not re.search(pattern, filename):
                    continue

            new_name = f"{prefix}_{filename}"
            new_path = os.path.join(target_directory, new_name)

            if os.path.exists(new_path):
                print(f"[FileAgent] Skip (exists): {new_name}")
                continue

            os.rename(file_path, new_path)
            print(f"[FileAgent] Renamed: {filename} → {new_name}")
            renamed += 1

        print(f"[FileAgent] Rename complete. {renamed} file(s) renamed.")

    def delete(self, file_path: str) -> None:
        if not os.path.isfile(file_path):
            print(f"[FileAgent] File not found: {file_path}")
            return
        os.remove(file_path)
        print(f"[FileAgent] Deleted: {file_path}")
