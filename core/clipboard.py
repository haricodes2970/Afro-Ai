import pyperclip


def get_text() -> str:
    try:
        text = pyperclip.paste()
        return text.strip() if isinstance(text, str) else ""
    except Exception as e:
        print(f"[Clipboard] Read failed: {e}")
        return ""


def set_text(text: str) -> None:
    try:
        pyperclip.copy(text)
    except Exception as e:
        print(f"[Clipboard] Write failed: {e}")
