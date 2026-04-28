import os
import sys
import time
import random

import pyautogui

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pyautogui.FAILSAFE = True
pyautogui.PAUSE    = 0.1

_WINDOW_TITLE = "Visual Studio Code"
_FOCUS_DELAY  = 0.5   # seconds after focusing before sending keys
_ACTION_DELAY = 0.15  # pause between chained actions


def _get_synth():
    try:
        from voice.synthesizer import VoiceSynthesizer
        return VoiceSynthesizer()
    except Exception:
        return None


def _speak(synth, text: str) -> None:
    if synth:
        try:
            synth.speak(text)
            return
        except Exception:
            pass
    print(f"[IDEController] {text}")


class IDEController:

    def __init__(self, synth=None):
        self._synth = synth or _get_synth()
        self._window = None

    # ── Window Detection ────────────────────────────────────────────

    def _find_window(self):
        try:
            import pygetwindow as gw
            matches = [
                w for w in gw.getAllWindows()
                if _WINDOW_TITLE.lower() in w.title.lower()
            ]
            return matches[0] if matches else None
        except Exception as e:
            print(f"[IDEController] Window search error: {e}", file=sys.stderr)
            return None

    def _focus_window(self) -> bool:
        win = self._find_window()
        if win is None:
            _speak(self._synth, "I can't find Visual Studio Code. Please open it.")
            self._window = None
            return False

        try:
            if win.isMinimized:
                win.restore()
                time.sleep(0.3)
            win.activate()
            time.sleep(_FOCUS_DELAY)
            self._window = win
            return True
        except Exception as e:
            print(f"[IDEController] Focus error: {e}", file=sys.stderr)
            _speak(self._synth, "I lost focus on Visual Studio Code.")
            self._window = None
            return False

    def _ensure_focused(self) -> bool:
        """Validate window is still active; re-focus if needed."""
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active and _WINDOW_TITLE.lower() in active.title.lower():
                return True
        except Exception:
            pass
        # Active window is not VS Code — attempt re-focus
        return self._focus_window()

    # ── Public API ──────────────────────────────────────────────────

    def create_file(self) -> bool:
        """Open a new untitled file with Ctrl+N."""
        if not self._ensure_focused():
            return False
        try:
            pyautogui.hotkey("ctrl", "n")
            time.sleep(_ACTION_DELAY)
            print("[IDEController] New file created.")
            return True
        except pyautogui.FailSafeException:
            print("[IDEController] Failsafe triggered during create_file.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[IDEController] create_file error: {e}", file=sys.stderr)
            return False

    def type_code(self, text: str, typing_speed: float = 0.03) -> bool:
        """
        Type text with simulated human delay between keystrokes.
        typing_speed is the base delay in seconds (jitter ±50% applied).
        """
        if not text:
            return True
        if not self._ensure_focused():
            return False

        speed = max(0.01, min(0.05, float(typing_speed)))

        try:
            for char in text:
                pyautogui.typewrite(char, interval=0)
                jitter = random.uniform(speed * 0.5, speed * 1.5)
                time.sleep(jitter)

            print(f"[IDEController] Typed {len(text)} character(s).")
            return True
        except pyautogui.FailSafeException:
            print("[IDEController] Failsafe triggered during type_code.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[IDEController] type_code error: {e}", file=sys.stderr)
            return False

    def save_file(self) -> bool:
        """Save current file with Ctrl+S."""
        if not self._ensure_focused():
            return False
        try:
            pyautogui.hotkey("ctrl", "s")
            time.sleep(_ACTION_DELAY)
            print("[IDEController] File saved.")
            return True
        except pyautogui.FailSafeException:
            print("[IDEController] Failsafe triggered during save_file.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[IDEController] save_file error: {e}", file=sys.stderr)
            return False

    def toggle_terminal(self) -> bool:
        """Toggle integrated terminal with Ctrl+`."""
        if not self._ensure_focused():
            return False
        try:
            pyautogui.hotkey("ctrl", "`")
            time.sleep(_ACTION_DELAY)
            print("[IDEController] Terminal toggled.")
            return True
        except pyautogui.FailSafeException:
            print("[IDEController] Failsafe triggered during toggle_terminal.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[IDEController] toggle_terminal error: {e}", file=sys.stderr)
            return False

    # ── Compound helpers ────────────────────────────────────────────

    def open_and_type(self, text: str, save: bool = True) -> bool:
        """Create new file, type code into it, optionally save."""
        if not self.create_file():
            return False
        time.sleep(0.2)
        if not self.type_code(text):
            return False
        if save:
            time.sleep(0.1)
            return self.save_file()
        return True
