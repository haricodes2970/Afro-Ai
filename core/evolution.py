import os
import sys
import subprocess
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SKILL_INDICATORS = [
    os.path.join(REPO_ROOT, "agents"),
    os.path.join(REPO_ROOT, "core"),
    os.path.join(REPO_ROOT, "voice"),
    os.path.join(REPO_ROOT, "communication"),
]


def _git(args: list[str], cwd: str = REPO_ROOT) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def has_uncommitted_changes() -> bool:
    code, out, _ = _git(["status", "--porcelain"])
    return code == 0 and bool(out)


def get_new_skill_files() -> list[str]:
    """Return untracked .py files in skill directories."""
    code, out, _ = _git(["status", "--porcelain"])
    if code != 0 or not out:
        return []

    new_files = []
    for line in out.splitlines():
        status = line[:2].strip()
        path = line[3:].strip().strip('"')
        if status == "??" and path.endswith(".py"):
            abs_path = os.path.join(REPO_ROOT, path)
            for skill_dir in SKILL_INDICATORS:
                if abs_path.startswith(skill_dir):
                    new_files.append(path)
                    break
    return new_files


def commit_self(message: str, files: list[str] | None = None) -> bool:
    """
    Stage and commit. If files is None, stages all tracked + new skill files.
    Returns True on success.
    """
    if not message or not message.strip():
        message = f"feat: Afro self-evolution commit {datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    if files:
        for f in files:
            code, _, err = _git(["add", f])
            if code != 0:
                print(f"[Evolution] git add failed for {f}: {err}", file=sys.stderr)
    else:
        new_skills = get_new_skill_files()
        for f in new_skills:
            _git(["add", f])
        _git(["add", "-u"])

    code, _, err = _git(["commit", "-m", message])
    if code != 0:
        print(f"[Evolution] git commit failed: {err}", file=sys.stderr)
        return False

    print(f"[Evolution] Committed: {message}")

    code, _, err = _git(["push", "origin", "master"])
    if code != 0:
        print(f"[Evolution] git push failed: {err}", file=sys.stderr)
        return False

    print("[Evolution] Pushed to origin/master.")
    return True


def evolve_on_new_skill(skill_description: str = "") -> bool:
    """
    Call this after Afro creates a new agent or prompt file.
    Auto-commits and pushes if new skill files are detected.
    """
    new_files = get_new_skill_files()
    if not new_files:
        print("[Evolution] No new skill files detected.")
        return False

    file_list = ", ".join(os.path.basename(f) for f in new_files)
    message = (
        f"feat: self-evolved new skill(s) — {file_list}"
        if not skill_description
        else f"feat: {skill_description}"
    )
    return commit_self(message, files=new_files)
