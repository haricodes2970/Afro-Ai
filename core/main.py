import os
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import sys
import time
import threading
import warnings
warnings.filterwarnings("ignore")

from datetime import datetime

import numpy as np
import pyaudio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice.listener import VoiceListener, FRAME_LENGTH, DETECTION_THRESHOLD
from voice.transcribe import process_speech
from voice.synthesizer import VoiceSynthesizer
from core.intent_router import IntentRouter
from core.system_tray import start_tray
from core.dashboard import start_dashboard, log_brain, socketio
from core.memory import log_command, update_output, update_feedback, remember
from core.watcher import Watcher
from core.hud import start_hud, stop_hud
from agents.process_agent import ProcessAgent, stop_deep_focus
from agents.dev_agent import DevAgent
from agents.meta_agent import start_meta_agent, run_review_on_command
from agents.scheduler_agent import SchedulerAgent

SAMPLE_RATE = 16000
CAPTURE_SECONDS = 5
CHUNK = 1024

_synth         = VoiceSynthesizer()
_intent_router = IntentRouter()
_watcher       = Watcher(synth=_synth)
_scheduler     = SchedulerAgent(synth=_synth)

deep_focus_active              = False
_focus_agent: ProcessAgent | None    = None
_focus_thread: threading.Thread | None = None
_listener: "AfroListener | None"     = None


@socketio.on("set_mute")
def _on_set_mute(data):
    _synth.mute(bool(data.get("muted", False)))


@socketio.on("set_speed")
def _on_set_speed(data):
    try:
        _synth.set_speed(float(data.get("speed", 1.0)))
    except (TypeError, ValueError):
        pass


PROCESS_OP_KEYWORDS = {
    "status":   "STATUS",
    "kill":     "KILL",
    "terminate":"KILL",
    "stop":     "KILL",
    "optimize": "OPTIMIZE",
    "clean up": "OPTIMIZE",
    "cleanup":  "OPTIMIZE",
}


def capture_audio() -> bytes:
    audio  = pyaudio.PyAudio()
    stream = None
    frames = []

    try:
        stream = audio.open(
            rate=SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=CHUNK,
        )
        num_chunks = int(SAMPLE_RATE / CHUNK * CAPTURE_SECONDS)
        for _ in range(num_chunks):
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
            except OSError as e:
                print(f"[Audio read error] {e}")
    except OSError as e:
        print(f"[Microphone error] {e}")
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        try:
            audio.terminate()
        except Exception:
            pass

    return b"".join(frames)


def _extract_process_op(text: str) -> tuple[str, str]:
    lower = text.lower()
    op = "STATUS"
    for keyword, operation in PROCESS_OP_KEYWORDS.items():
        if keyword in lower:
            op = operation
            break

    process_name = ""
    if op == "KILL":
        words = lower.split()
        for i, word in enumerate(words):
            if word in ("kill", "terminate", "stop") and i + 1 < len(words):
                process_name = words[i + 1]
                break

    return op, process_name


def _handle_process_ops(transcribed_text: str, row_id: int) -> None:
    agent = ProcessAgent()
    op, process_name = _extract_process_op(transcribed_text)

    if op == "STATUS":
        agent.status()
        _synth.speak("Here are the top running processes.")
        update_output(row_id, "STATUS displayed")
        update_feedback(row_id, True)

    elif op == "KILL":
        if not process_name:
            _synth.speak("Please specify a process name to kill.")
            update_feedback(row_id, False)
            return
        freed_mb = agent.kill(process_name)
        if freed_mb > 0:
            _synth.speak(f"Process terminated. Freed {freed_mb:.0f} MB RAM")
            update_output(row_id, f"Killed {process_name}, freed {freed_mb:.1f} MB")
            update_feedback(row_id, True)
        else:
            _synth.speak(f"Could not find process {process_name}")
            update_feedback(row_id, False)

    elif op == "OPTIMIZE":
        freed_mb = agent.optimize()
        if freed_mb > 0:
            _synth.speak(f"Optimization complete. Freed {freed_mb:.0f} MB RAM")
            update_output(row_id, f"Freed {freed_mb:.1f} MB")
            update_feedback(row_id, True)
        else:
            _synth.speak("No bloatware processes found running.")
            update_feedback(row_id, False)


def _handle_dev_ops(intent_label: str, transcribed_text: str, row_id: int) -> None:
    agent = DevAgent()

    if intent_label == "DEV_OPTIMIZE" or "optimize this" in transcribed_text.lower():
        _synth.speak("Analyzing code on clipboard...")
        log_brain(f"DEV_OPTIMIZE triggered: {transcribed_text[:60]}")
        result = agent.optimize_code()
        if result:
            _synth.speak("Code optimized and ready to paste.")
            log_brain("DEV_OPTIMIZE complete.")
            update_output(row_id, result[:500])
            update_feedback(row_id, True)
        else:
            _synth.speak("Clipboard was empty or optimization failed.")
            log_brain("DEV_OPTIMIZE failed — empty clipboard or LLM error.")
            update_feedback(row_id, False)

    elif intent_label == "DEV_EXPLAIN":
        _synth.speak("Analyzing code on clipboard...")
        log_brain(f"DEV_EXPLAIN triggered: {transcribed_text[:60]}")
        result = agent.explain_code()
        if result:
            _synth.speak("Explanation ready. Check your clipboard.")
            log_brain("DEV_EXPLAIN complete.")
            update_output(row_id, result[:500])
            update_feedback(row_id, True)
        else:
            _synth.speak("Clipboard was empty or explanation failed.")
            log_brain("DEV_EXPLAIN failed.")
            update_feedback(row_id, False)

    elif intent_label == "DEV_DEBUG":
        _synth.speak("Analyzing code on clipboard...")
        log_brain(f"DEV_DEBUG triggered: {transcribed_text[:60]}")
        result = agent.debug_code()
        if result:
            _synth.speak("Debug complete. Fixed code is ready to paste.")
            log_brain("DEV_DEBUG complete.")
            update_output(row_id, result[:500])
            update_feedback(row_id, True)
        else:
            _synth.speak("Clipboard was empty or debug failed.")
            log_brain("DEV_DEBUG failed.")
            update_feedback(row_id, False)


def _handle_remember(transcribed_text: str) -> None:
    lower  = transcribed_text.lower()
    marker = "remember this"
    idx    = lower.find(marker)

    if idx != -1:
        content = transcribed_text[idx + len(marker):].strip(" ,.:")
    else:
        content = transcribed_text.strip()

    if not content:
        _synth.speak("What should I remember? Please say the content after 'remember this'.")
        return

    stored = remember(content)
    if stored:
        _synth.speak("Got it. I'll remember that.")
        log_brain(f"Remembered: {content[:80]}")
        print(f"[Memory] Stored: {content}")
    else:
        _synth.speak("I already have that in memory.")
        log_brain(f"Already remembered: {content[:80]}")


def _activate_deep_focus() -> None:
    global deep_focus_active, _focus_agent, _focus_thread
    if deep_focus_active:
        return
    deep_focus_active = True
    _focus_agent  = ProcessAgent()
    start_hud(focus_start=datetime.now())
    _focus_thread = threading.Thread(
        target=_focus_agent.enforce_deep_focus,
        daemon=True,
        name="AfroDeepFocus",
    )
    _focus_thread.start()
    log_brain("Deep Focus mode activated.")
    print("[Main] Deep Focus mode ACTIVE.")


def _deactivate_deep_focus() -> None:
    global deep_focus_active
    if not deep_focus_active:
        return
    deep_focus_active = False
    stop_deep_focus()
    stop_hud()
    log_brain("Deep Focus mode deactivated.")
    print("[Main] Deep Focus mode STANDBY.")


def on_wake_word_detected() -> None:
    _synth.speak("Listening...")
    log_brain("Wake word detected.")

    print("Capturing command...")
    audio_data = capture_audio()

    if not audio_data:
        print("[Warning] No audio captured.")
        log_brain("Warning: no audio captured.")
        return

    try:
        transcribed_text = process_speech(audio_data)
    except Exception as e:
        print(f"[Transcription error] {e}")
        log_brain(f"Transcription error: {e}")
        return

    if not transcribed_text:
        print("[Warning] Empty transcription.")
        log_brain("Warning: empty transcription.")
        return

    print(f"User said: {transcribed_text}")
    log_brain(f"User: {transcribed_text}")

    lower = transcribed_text.lower()

    # ── special commands (pre-routing) ───────────────────────────

    if "remember this" in lower:
        row_id = log_command(transcribed_text, "REMEMBER")
        _handle_remember(transcribed_text)
        update_feedback(row_id, True)
        return

    if lower.startswith("remind me") or "remind me to" in lower or "remind me about" in lower:
        row_id = log_command(transcribed_text, "REMINDER")
        threading.Thread(
            target=_scheduler.handle_voice_command,
            args=(transcribed_text,),
            daemon=True,
        ).start()
        update_feedback(row_id, True)
        return

    if "review logs" in lower or "run meta review" in lower:
        row_id = log_command(transcribed_text, "META_REVIEW")
        _synth.speak("Running system review. This may take a moment.")
        threading.Thread(
            target=lambda: (
                run_review_on_command(),
                _synth.speak("Review complete. Check logs for suggestions."),
                update_feedback(row_id, True),
            ),
            daemon=True,
        ).start()
        return

    # ── focus mode commands (pre-routing) ────────────────────────
    if any(k in lower for k in ("enter deep focus", "deep focus mode", "focus mode", "start focus")):
        row_id = log_command(transcribed_text, "ENTER_FOCUS")
        threading.Thread(target=_activate_deep_focus, daemon=True).start()
        _synth.speak("Deep Focus mode activated.")
        update_feedback(row_id, True)
        return

    if any(k in lower for k in ("standby", "exit focus", "stop focus", "leave focus", "deactivate focus")):
        row_id = log_command(transcribed_text, "EXIT_FOCUS")
        threading.Thread(target=_deactivate_deep_focus, daemon=True).start()
        _synth.speak("Returning to normal mode.")
        update_feedback(row_id, True)
        return

    # ── normal intent routing ─────────────────────────────────────
    intent_label = _intent_router.route(transcribed_text)
    print(f"Intent: {intent_label}")
    log_brain(f"Intent: {intent_label}")

    row_id = log_command(transcribed_text, intent_label)

    if intent_label == "ENTER_FOCUS":
        threading.Thread(target=_activate_deep_focus, daemon=True).start()
        _synth.speak("Deep Focus mode activated.")
        update_feedback(row_id, True)
    elif intent_label == "EXIT_FOCUS":
        threading.Thread(target=_deactivate_deep_focus, daemon=True).start()
        _synth.speak("Returning to normal mode.")
        update_feedback(row_id, True)
    elif intent_label == "PROCESS_OPS":
        _handle_process_ops(transcribed_text, row_id)
    elif intent_label in ("DEV_OPTIMIZE", "DEV_EXPLAIN", "DEV_DEBUG"):
        threading.Thread(
            target=_handle_dev_ops,
            args=(intent_label, transcribed_text, row_id),
            daemon=True,
        ).start()
    else:
        _synth.speak(f"Routing to {intent_label}")
        update_feedback(row_id, True)


class AfroListener(VoiceListener):
    """Extends VoiceListener to trigger a callback on wake-word detection."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def _detection_loop(self):
        print("Listening for wake word...")
        while not self._shutdown:
            try:
                raw = self.stream.read(FRAME_LENGTH, exception_on_overflow=False)
                frame = np.frombuffer(raw, dtype=np.int16)
                prediction = self.oww_model.predict(frame)

                for _model_name, score in prediction.items():
                    if score >= DETECTION_THRESHOLD:
                        print("\n=========================")
                        print("AFRO IS ACTIVE")
                        print("=========================\n")
                        self.oww_model.reset()
                        self._callback()
                        break

            except OSError as e:
                if self._shutdown:
                    break
                print(f"[Audio error] {e}")
                time.sleep(0.1)


def _shutdown_all(listener: "AfroListener | None" = None) -> None:
    print("\nAfro shutting down...")
    if deep_focus_active:
        try:
            _deactivate_deep_focus()
        except Exception:
            pass
    if listener is not None:
        try:
            listener._shutdown = True
            listener._cleanup()
        except Exception:
            pass


def main() -> None:
    global _listener

    print("Project Afro Starting...")

    start_tray()
    print("System tray initialized.")

    start_dashboard()
    print("Dashboard running at http://127.0.0.1:5000")
    log_brain("Afro system started.")

    start_meta_agent()
    print("Meta-agent scheduled (24h review cycle).")

    _watcher.start()
    print("Proactive watcher started.")

    _scheduler.run_loop()
    print("Scheduler agent started.")

    print("Initializing voice system...")
    _listener = AfroListener(callback=on_wake_word_detected)

    try:
        _listener.start()
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown_all(_listener)
        os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[Fatal] {e}")
        os._exit(1)
