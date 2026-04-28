import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "memory.db")

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _lock:
        con = _conn()
        con.executescript("""
            CREATE TABLE IF NOT EXISTS commands (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                command     TEXT    NOT NULL,
                intent      TEXT,
                output      TEXT,
                feedback    INTEGER DEFAULT 0,
                pinned      INTEGER DEFAULT 0,
                note        TEXT
            );

            CREATE TABLE IF NOT EXISTS long_term (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                content     TEXT    NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at     TEXT    NOT NULL,
                reminder_text  TEXT    NOT NULL,
                due_at         TEXT    NOT NULL,
                completed      INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_intent       ON commands(intent);
            CREATE INDEX IF NOT EXISTS idx_timestamp    ON commands(timestamp);
            CREATE INDEX IF NOT EXISTS idx_reminder_due ON reminders(due_at);
        """)
        con.commit()
        con.close()


def log_command(command: str, intent: str = "", output: str = "") -> int:
    with _lock:
        con = _conn()
        cur = con.execute(
            "INSERT INTO commands (timestamp, command, intent, output) VALUES (?,?,?,?)",
            (datetime.utcnow().isoformat(), command, intent, output),
        )
        row_id = cur.lastrowid
        con.commit()
        con.close()
    return row_id


def update_feedback(row_id: int, success: bool) -> None:
    with _lock:
        con = _conn()
        con.execute(
            "UPDATE commands SET feedback = ? WHERE id = ?",
            (1 if success else -1, row_id),
        )
        con.commit()
        con.close()


def update_output(row_id: int, output: str) -> None:
    with _lock:
        con = _conn()
        con.execute("UPDATE commands SET output = ? WHERE id = ?", (output, row_id))
        con.commit()
        con.close()


def remember(content: str) -> bool:
    """Pin content to long-term memory. Returns True if newly stored."""
    content = content.strip()
    if not content:
        return False
    with _lock:
        con = _conn()
        try:
            con.execute(
                "INSERT INTO long_term (timestamp, content) VALUES (?,?)",
                (datetime.utcnow().isoformat(), content),
            )
            con.commit()
            stored = True
        except sqlite3.IntegrityError:
            stored = False
        finally:
            con.close()
    return stored


def get_long_term() -> list[dict]:
    with _lock:
        con = _conn()
        rows = con.execute(
            "SELECT * FROM long_term ORDER BY timestamp DESC"
        ).fetchall()
        con.close()
    return [dict(r) for r in rows]


def get_recent_commands(limit: int = 100) -> list[dict]:
    with _lock:
        con = _conn()
        rows = con.execute(
            "SELECT * FROM commands ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        con.close()
    return [dict(r) for r in rows]


def get_failure_stats(limit: int = 500) -> dict[str, int]:
    """Return intent → failure count for meta-agent analysis."""
    with _lock:
        con = _conn()
        rows = con.execute(
            """
            SELECT intent, COUNT(*) as cnt
            FROM commands
            WHERE feedback = -1
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        con.close()
    return {r["intent"]: r["cnt"] for r in rows}


def add_reminder(reminder_text: str, due_iso: str) -> int:
    with _lock:
        con = _conn()
        cur = con.execute(
            "INSERT INTO reminders (created_at, reminder_text, due_at) VALUES (?,?,?)",
            (datetime.utcnow().isoformat(), reminder_text, due_iso),
        )
        rid = cur.lastrowid
        con.commit()
        con.close()
    return rid


def get_due_reminders() -> list[dict]:
    now_iso = datetime.utcnow().isoformat()
    with _lock:
        con = _conn()
        rows = con.execute(
            "SELECT * FROM reminders WHERE due_at <= ? AND completed = 0",
            (now_iso,),
        ).fetchall()
        con.close()
    return [dict(r) for r in rows]


def complete_reminder(rid: int) -> None:
    with _lock:
        con = _conn()
        con.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (rid,))
        con.commit()
        con.close()


# Initialise on import
init_db()
