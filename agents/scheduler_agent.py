import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.memory import add_reminder, get_due_reminders, complete_reminder

LOOP_INTERVAL = 30

_TIME_PATTERNS = [
    (r"in (\d+)\s*second",     lambda m: timedelta(seconds=int(m.group(1)))),
    (r"in (\d+)\s*minute",     lambda m: timedelta(minutes=int(m.group(1)))),
    (r"in (\d+)\s*hour",       lambda m: timedelta(hours=int(m.group(1)))),
    (r"in half an hour",        lambda _: timedelta(minutes=30)),
    (r"in an?\s*hour",          lambda _: timedelta(hours=1)),
]

_TIME_CLAUSE_RE = re.compile(
    r"\s*(in \d+\s*(second|minute|hour)s?"
    r"|in half an hour"
    r"|in an?\s*hour)\s*",
    re.IGNORECASE,
)


class SchedulerAgent:

    def __init__(self, synth=None):
        self._synth = synth

    def parse_command(self, text: str) -> tuple[str, datetime | None]:
        lower = text.lower()
        due: datetime | None = None

        for pattern, delta_fn in _TIME_PATTERNS:
            m = re.search(pattern, lower)
            if m:
                due = datetime.now() + delta_fn(m)
                break

        # Strip "remind me (to|about)?" prefix
        reminder_text = re.sub(
            r"^\s*remind me\s+(to\s+|about\s+)?",
            "",
            lower,
            flags=re.IGNORECASE,
        ).strip()

        # Strip the time clause from the text
        reminder_text = _TIME_CLAUSE_RE.sub(" ", reminder_text).strip(" .,")

        return reminder_text, due

    def schedule(self, reminder_text: str, reminder_time: datetime) -> int:
        rid = add_reminder(reminder_text, reminder_time.isoformat())
        print(
            f"[Scheduler] Set: '{reminder_text}' "
            f"due {reminder_time.strftime('%H:%M:%S')}"
        )
        return rid

    def handle_voice_command(self, text: str) -> bool:
        reminder_text, due = self.parse_command(text)
        if not reminder_text or due is None:
            self._speak("I need a time for the reminder, like 'in 20 minutes'.")
            return False
        self.schedule(reminder_text, due)
        mins = int((due - datetime.now()).total_seconds() / 60)
        self._speak(f"Got it. I'll remind you to {reminder_text} in {mins} minutes.")
        return True

    def _speak(self, text: str) -> None:
        if self._synth:
            threading.Thread(target=self._synth.speak, args=(text,), daemon=True).start()
        else:
            print(f"[Scheduler] {text}")

    def _tick(self) -> None:
        due_rows = get_due_reminders()
        for row in due_rows:
            self._speak(f"Reminder: {row['reminder_text']}")
            complete_reminder(row["id"])
            print(f"[Scheduler] Fired #{row['id']}: {row['reminder_text']}")

    def run_loop(self) -> threading.Thread:
        def _loop():
            while True:
                try:
                    self._tick()
                except Exception as e:
                    print(f"[Scheduler] Loop error: {e}", file=sys.stderr)
                time.sleep(LOOP_INTERVAL)

        t = threading.Thread(target=_loop, daemon=True, name="AfroScheduler")
        t.start()
        return t
