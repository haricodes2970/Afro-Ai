import os
import sys
import time

import pyautogui

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.ide_controller import IDEController
from voice.synthesizer import VoiceSynthesizer

_EXECUTION_STATES = ("IDLE", "UPDATING", "REBOOTING")


class EvolutionEngine:

    def __init__(self, synth: VoiceSynthesizer | None = None):
        self._synth = synth or VoiceSynthesizer()
        self._ide   = IDEController(synth=self._synth)
        self._state = "IDLE"

    # ── Internal helpers ────────────────────────────────────────────

    def _say(self, text: str) -> None:
        try:
            self._synth.speak(text)
        except Exception as e:
            print(f"[EvolutionEngine] Speak error: {e}", file=sys.stderr)

    def _set_state(self, state: str) -> None:
        if state in _EXECUTION_STATES:
            self._state = state
            print(f"[EvolutionEngine] State → {state}")

    # ── Public API ──────────────────────────────────────────────────

    def apply_self_upgrade(self, target_path: str, code_snippet: str) -> bool:
        if self._state != "IDLE":
            self._say("An upgrade is already in progress. Please wait.")
            return False

        if not target_path or not code_snippet:
            self._say("Missing target path or code snippet. Aborting upgrade.")
            return False

        self._set_state("UPDATING")

        try:
            # STEP 1 — Voice notification
            self._say("Updating my system logic now.")

            # STEP 2 — Open file in VS Code
            self._say("Opening Visual Studio Code.")
            if not self._ide.open_vscode(target_path):
                self._say("Failed to open Visual Studio Code. Aborting.")
                self._set_state("IDLE")
                return False
            time.sleep(1.0)

            # STEP 3 — Focus editor
            self._say("Focusing editor.")
            if not self._ide.focus_editor():
                self._say("Could not focus the editor. Aborting upgrade.")
                self._set_state("IDLE")
                return False

            # STEP 4 — Stabilization delay
            time.sleep(0.5)

            # STEP 5 — Move cursor to end of file and append code
            self._say("Applying changes.")
            try:
                pyautogui.hotkey("ctrl", "end")
                time.sleep(0.15)
            except pyautogui.FailSafeException:
                self._say("Failsafe triggered. Aborting upgrade.")
                self._set_state("IDLE")
                return False
            except Exception as e:
                print(f"[EvolutionEngine] cursor-end error: {e}", file=sys.stderr)

            if not self._ide.type_code("\n\n" + code_snippet):
                self._say("Failed to write code to editor. Aborting.")
                self._set_state("IDLE")
                return False

            time.sleep(0.2)

            # STEP 6 — Save file
            self._say("Saving file.")
            if not self._ide.save_file():
                self._say("Failed to save the file. Aborting.")
                self._set_state("IDLE")
                return False

            time.sleep(0.15)

            # STEP 7 — Completion feedback
            self._say("Upgrade complete.")
            print(f"[EvolutionEngine] Self-upgrade applied to: {target_path}")
            self._set_state("IDLE")
            return True

        except Exception as e:
            print(f"[EvolutionEngine] apply_self_upgrade failed: {e}", file=sys.stderr)
            self._say(f"Upgrade failed due to an error. Check the console.")
            self._set_state("IDLE")
            return False

    def trigger_reboot(self) -> None:
        if self._state == "REBOOTING":
            return

        self._set_state("REBOOTING")

        try:
            # STEP 1 — Voice notification
            self._say("Rebooting to apply updates.")
            time.sleep(1.5)

            # STEP 2 — Full process replacement (no subprocess)
            print("[EvolutionEngine] Replacing process via os.execv...")
            os.execv(sys.executable, ["python"] + sys.argv)

        except Exception as e:
            print(f"[EvolutionEngine] trigger_reboot failed: {e}", file=sys.stderr)
            self._say("Reboot failed. Please restart manually.")
            self._set_state("IDLE")
