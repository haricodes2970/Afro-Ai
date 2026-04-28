import re

import pyperclip

MAX_CLIPBOARD_CHARS = 8000


def get_clipboard_text() -> str:
    try:
        text = pyperclip.paste()
        return text if isinstance(text, str) else ""
    except Exception as e:
        print(f"[ClipboardAgent] Read failed: {e}")
        return ""


def set_clipboard_text(text: str) -> None:
    try:
        pyperclip.copy(text)
    except Exception as e:
        print(f"[ClipboardAgent] Write failed: {e}")


def get_code_context() -> str:
    raw = get_clipboard_text()
    if not raw or not raw.strip():
        return ""

    # collapse runs of 3+ blank lines to 2
    sanitized = re.sub(r'\n{3,}', '\n\n', raw)

    # strip windows carriage returns
    sanitized = sanitized.replace('\r\n', '\n').replace('\r', '\n')

    # remove zero-width and non-printable chars (keep tabs and newlines)
    sanitized = re.sub(r'[^\S\t\n ]+', ' ', sanitized)
    sanitized = re.sub(r'[ \t]+$', '', sanitized, flags=re.MULTILINE)

    # hard cap
    if len(sanitized) > MAX_CLIPBOARD_CHARS:
        sanitized = sanitized[:MAX_CLIPBOARD_CHARS]
        sanitized += "\n\n# [clipped — exceeded max context size]"

    return sanitized.strip()
