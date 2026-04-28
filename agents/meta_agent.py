import os
import sys
import glob
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.memory import get_failure_stats, get_recent_commands
from core.llm_factory import LLMFactory

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
SUGGESTIONS_FILE = os.path.join(LOGS_DIR, "meta_suggestions.txt")
REVIEW_INTERVAL_SECONDS = 86400  # 24 hours

_factory = LLMFactory()

ANALYSIS_PROMPT = (
    "You are an AI system optimizer. Review the following failure data from an intent router "
    "and command history log. Identify:\n"
    "1. Intents that fail most often\n"
    "2. Missing keywords that should be added to routing logic\n"
    "3. System prompt updates that would improve classification\n\n"
    "Be concise. Output a numbered list of actionable suggestions only."
)


def _read_log_files(max_bytes: int = 20000) -> str:
    os.makedirs(LOGS_DIR, exist_ok=True)
    parts = []
    total = 0

    for log_file in sorted(glob.glob(os.path.join(LOGS_DIR, "*.log")), reverse=True):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(max_bytes - total)
                parts.append(f"[{os.path.basename(log_file)}]\n{content}")
                total += len(content)
                if total >= max_bytes:
                    break
        except OSError:
            continue

    return "\n\n".join(parts)


def _build_analysis_context() -> str:
    failure_stats = get_failure_stats(limit=500)
    recent = get_recent_commands(limit=50)

    failure_lines = "\n".join(
        f"  {intent or 'UNKNOWN'}: {count} failure(s)"
        for intent, count in sorted(failure_stats.items(), key=lambda x: -x[1])
    ) or "  No failures recorded."

    recent_lines = "\n".join(
        f"  [{r['timestamp'][:19]}] intent={r['intent'] or '?'} "
        f"feedback={r['feedback']} cmd={r['command'][:80]}"
        for r in recent[:20]
    ) or "  No commands recorded."

    log_content = _read_log_files()

    return (
        f"=== FAILURE STATS ===\n{failure_lines}\n\n"
        f"=== RECENT COMMANDS ===\n{recent_lines}\n\n"
        f"=== LOG FILES ===\n{log_content[:10000]}"
    )


def run_review() -> str:
    print("[MetaAgent] Running daily review...")
    os.makedirs(LOGS_DIR, exist_ok=True)

    context = _build_analysis_context()
    full_prompt = f"{ANALYSIS_PROMPT}\n\n{context}"

    suggestions = _factory.call("DEV_EXPLAIN", ANALYSIS_PROMPT, context)

    if not suggestions:
        suggestions = (
            "MetaAgent: LLM unavailable. Manual review of failure stats:\n"
            + context[:2000]
        )

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"\n{'='*60}\n[{timestamp}]\n{suggestions}\n"

    try:
        with open(SUGGESTIONS_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"[MetaAgent] Suggestions written to {SUGGESTIONS_FILE}")
    except OSError as e:
        print(f"[MetaAgent] Could not write suggestions: {e}")

    return suggestions


def run_review_on_command() -> str:
    """Trigger immediately on voice command."""
    return run_review()


def _daily_loop() -> None:
    while True:
        try:
            run_review()
        except Exception as e:
            print(f"[MetaAgent] Review error: {e}")
        time.sleep(REVIEW_INTERVAL_SECONDS)


def start_meta_agent() -> threading.Thread:
    t = threading.Thread(target=_daily_loop, daemon=True, name="AfroMetaAgent")
    t.start()
    return t
