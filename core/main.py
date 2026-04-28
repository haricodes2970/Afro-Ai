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
from core.dashboard import start_dashboard, log_brain, socketio, set_exec_state
from core.memory import log_command, update_output, update_feedback, remember
from core.watcher import Watcher
from core.hud import start_hud, stop_hud
from agents.process_agent import ProcessAgent, stop_deep_focus
from agents.dev_agent import DevAgent
from agents.meta_agent import start_meta_agent, run_review_on_command
from agents.scheduler_agent import SchedulerAgent
from agents.orchestrator import Orchestrator
from agents.os_agent import OSAgent

# ── PyQt6 / CockpitUI (optional) ─────────────────────────────────────────────
try:
    from PyQt6.QtCore import QObject, pyqtSignal
    from core.cockpit_ui import launch_cockpit
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False

SAMPLE_RATE     = 16000
CAPTURE_SECONDS = 5
CHUNK           = 1024

_synth         = VoiceSynthesizer()
_intent_router = IntentRouter()
_watcher       = Watcher(synth=_synth)
_scheduler     = SchedulerAgent(synth=_synth)

deep_focus_active                      = False
_focus_agent: ProcessAgent | None      = None
_focus_thread: threading.Thread | None = None
_listener: "AfroListener | None"       = None

# CockpitUI handles (populated in main() when Qt is available)
_qt_app  = None
_cockpit = None
_bridge: "object | None" = None   # _UiBridge instance


# ── UI bridge (Qt cross-thread signals) ──────────────────────────────────────

if _QT_AVAILABLE:
    class _UiBridge(QObject):
        speaking_changed    = pyqtSignal(bool)
        log_message         = pyqtSignal(str)
        agent_state_changed = pyqtSignal(str, str)


# ── Speak / log helpers ───────────────────────────────────────────────────────

def _speak(msg: str) -> None:
    """Speak via synthesizer and update CockpitUI orb if available."""
    if _bridge is not None:
        try:
            _bridge.speaking_changed.emit(True)
        except Exception:
            pass
    _synth.speak(msg)
    if _bridge is not None:
        try:
            _bridge.speaking_changed.emit(False)
        except Exception:
            pass


def _ui_log(msg: str) -> None:
    """Log to brain DB and CockpitUI log panel if available."""
    log_brain(msg)
    if _bridge is not None:
        try:
            _bridge.log_message.emit(msg)
        except Exception:
            pass


# ── SocketIO handlers ─────────────────────────────────────────────────────────

@socketio.on("set_mute")
def _on_set_mute(data):
    _synth.mute(bool(data.get("muted", False)))


@socketio.on("set_speed")
def _on_set_speed(data):
    try:
        _synth.set_speed(float(data.get("speed", 1.0)))
    except (TypeError, ValueError):
        pass


# ── Process-ops helpers ───────────────────────────────────────────────────────

PROCESS_OP_KEYWORDS = {
    "status":    "STATUS",
    "kill":      "KILL",
    "terminate": "KILL",
    "stop":      "KILL",
    "optimize":  "OPTIMIZE",
    "clean up":  "OPTIMIZE",
    "cleanup":   "OPTIMIZE",
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


def _keyword_route_fallback(lower: str) -> str:
    if any(k in lower for k in ("optimize", "refactor", "improve", "clean up code")):
        return "DEV_OPTIMIZE"
    if any(k in lower for k in ("explain", "what does", "how does", "what is")):
        return "DEV_EXPLAIN"
    if any(k in lower for k in ("debug", "fix", "error", "bug", "broken")):
        return "DEV_DEBUG"
    if any(k in lower for k in ("process", "cpu", "memory", "ram", "kill", "terminate")):
        return "PROCESS_OPS"
    if any(k in lower for k in ("deep focus", "focus mode", "enter focus", "start focus")):
        return "ENTER_FOCUS"
    if any(k in lower for k in ("standby", "exit focus", "stop focus", "leave focus")):
        return "EXIT_FOCUS"
    return "UNKNOWN"


def _is_api_error(e: Exception) -> bool:
    err  = str(e).lower()
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    return (
        code == 429
        or "429" in err
        or "quota" in err
        or ("rate" in err and "limit" in err)
        or isinstance(e, (ConnectionError, TimeoutError))
        or "connection" in err
        or "timeout" in err
    )


# ── Command handlers ──────────────────────────────────────────────────────────

def _handle_process_ops(transcribed_text: str, row_id: int) -> None:
    agent = ProcessAgent()
    op, process_name = _extract_process_op(transcribed_text)

    if op == "STATUS":
        agent.status()
        _speak("Here are the top running processes.")
        update_output(row_id, "STATUS displayed")
        update_feedback(row_id, True)

    elif op == "KILL":
        if not process_name:
            _speak("Please specify a process name to kill.")
            update_feedback(row_id, False)
            return
        freed_mb = agent.kill(process_name)
        if freed_mb > 0:
            _speak(f"Process terminated. Freed {freed_mb:.0f} MB RAM")
            update_output(row_id, f"Killed {process_name}, freed {freed_mb:.1f} MB")
            update_feedback(row_id, True)
        else:
            _speak(f"Could not find process {process_name}")
            update_feedback(row_id, False)

    elif op == "OPTIMIZE":
        freed_mb = agent.optimize()
        if freed_mb > 0:
            _speak(f"Optimization complete. Freed {freed_mb:.0f} MB RAM")
            update_output(row_id, f"Freed {freed_mb:.1f} MB")
            update_feedback(row_id, True)
        else:
            _speak("No bloatware processes found running.")
            update_feedback(row_id, False)


def _handle_dev_ops(intent_label: str, transcribed_text: str, row_id: int) -> None:
    agent = DevAgent()

    try:
        if intent_label == "DEV_OPTIMIZE" or "optimize this" in transcribed_text.lower():
            _speak("Analyzing code on clipboard...")
            _ui_log(f"DEV_OPTIMIZE triggered: {transcribed_text[:60]}")
            result = agent.optimize_code()
            if result:
                _speak("Code optimized and ready to paste.")
                _ui_log("DEV_OPTIMIZE complete.")
                update_output(row_id, result[:500])
                update_feedback(row_id, True)
            else:
                _speak("Clipboard was empty or optimization failed.")
                _ui_log("DEV_OPTIMIZE failed — empty clipboard or LLM error.")
                update_feedback(row_id, False)

        elif intent_label == "DEV_EXPLAIN":
            _speak("Analyzing code on clipboard...")
            _ui_log(f"DEV_EXPLAIN triggered: {transcribed_text[:60]}")
            result = agent.explain_code()
            if result:
                _speak("Explanation ready. Check your clipboard.")
                _ui_log("DEV_EXPLAIN complete.")
                update_output(row_id, result[:500])
                update_feedback(row_id, True)
            else:
                _speak("Clipboard was empty or explanation failed.")
                _ui_log("DEV_EXPLAIN failed.")
                update_feedback(row_id, False)

        elif intent_label == "DEV_DEBUG":
            _speak("Analyzing code on clipboard...")
            _ui_log(f"DEV_DEBUG triggered: {transcribed_text[:60]}")
            result = agent.debug_code()
            if result:
                _speak("Debug complete. Fixed code is ready to paste.")
                _ui_log("DEV_DEBUG complete.")
                update_output(row_id, result[:500])
                update_feedback(row_id, True)
            else:
                _speak("Clipboard was empty or debug failed.")
                _ui_log("DEV_DEBUG failed.")
                update_feedback(row_id, False)

    except (ConnectionError, TimeoutError) as e:
        _ui_log(f"Dev ops connection error: {e}")
        _speak("API quota exceeded. Falling back to local keyword engine.")
        set_exec_state("FAILED", "CONNECTION")
        update_feedback(row_id, False)
    except Exception as e:
        _ui_log(f"Dev ops error: {e}")
        if _is_api_error(e):
            _speak("API quota exceeded. Falling back to local keyword engine.")
            set_exec_state("FAILED", "API_QUOTA")
        else:
            _speak("Dev operation failed. Please try again.")
            set_exec_state("FAILED", "DEV_ERROR")
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
        _speak("What should I remember? Please say the content after 'remember this'.")
        return

    stored = remember(content)
    if stored:
        _speak("Got it. I'll remember that.")
        _ui_log(f"Remembered: {content[:80]}")
        print(f"[Memory] Stored: {content}")
    else:
        _speak("I already have that in memory.")
        _ui_log(f"Already remembered: {content[:80]}")


_OS_TRIGGER_KEYWORDS = (
    "sort my", "sort the", "organise", "organize",
    "create folder", "make folder", "make a folder",
    "install ", "upgrade yourself",
    "open vs code", "open vscode", "open visual studio",
    "clean up my", "clean my downloads",
)


def _handle_os_ops(transcribed_text: str, row_id: int) -> None:
    lower = transcribed_text.lower()

    if "upgrade yourself" in lower:
        agent = OSAgent()
        _speak("Opening VS Code to apply upgrades.")
        _ui_log("Upgrade self triggered.")
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        agent.open_vscode(project_root)
        update_output(row_id, "VS Code opened for self-upgrade")
        update_feedback(row_id, True)
        set_exec_state("SUCCESS", "VS Code opened")
        return

    if any(k in lower for k in ("open vs code", "open vscode", "open visual studio")):
        agent = OSAgent()
        _speak("Opening VS Code.")
        agent.open_vscode()
        update_output(row_id, "VS Code opened")
        update_feedback(row_id, True)
        set_exec_state("SUCCESS", "VS Code opened")
        return

    def _run():
        try:
            orch = Orchestrator()
            executed = orch.run_director_loop(transcribed_text, synth=_synth)
            update_output(row_id, "; ".join(executed) if executed else "no steps executed")
            update_feedback(row_id, bool(executed))
            _ui_log(f"OS_OPS director complete: {len(executed)} step(s)")
        except Exception as e:
            _ui_log(f"OS_OPS thread error: {e}")
            set_exec_state("FAILED", "OS_OPS error")
            update_feedback(row_id, False)

    threading.Thread(target=_run, daemon=True, name="AfroDirector").start()


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
    _ui_log("Deep Focus mode activated.")
    print("[Main] Deep Focus mode ACTIVE.")


def _deactivate_deep_focus() -> None:
    global deep_focus_active
    if not deep_focus_active:
        return
    deep_focus_active = False
    stop_deep_focus()
    stop_hud()
    _ui_log("Deep Focus mode deactivated.")
    print("[Main] Deep Focus mode STANDBY.")


# ── Wake-word callback ────────────────────────────────────────────────────────

def on_wake_word_detected() -> None:
    _speak("Listening...")
    _ui_log("Wake word detected.")

    print("Capturing command...")
    audio_data = capture_audio()

    if not audio_data:
        print("[Warning] No audio captured.")
        _ui_log("Warning: no audio captured.")
        return

    try:
        transcribed_text = process_speech(audio_data)
    except Exception as e:
        print(f"[Transcription error] {e}")
        _ui_log(f"Transcription error: {e}")
        return

    if not transcribed_text:
        print("[Warning] Empty transcription.")
        _ui_log("Warning: empty transcription.")
        return

    print(f"User said: {transcribed_text}")
    _ui_log(f"User: {transcribed_text}")

    lower = transcribed_text.lower()

    # ── local-first fast path (no API call) ──────────────────────
    try:
        from agents.local_router import match_local_intent
        local_result = match_local_intent(transcribed_text)
        if isinstance(local_result, dict) and local_result.get("status") == "HANDLED":
            action  = local_result.get("action", "local")
            details = local_result.get("details", {})
            row_id  = log_command(transcribed_text, action.upper())
            _ui_log(f"Local: {action} {details}")
            update_feedback(row_id, True)
            return
    except Exception as e:
        _ui_log(f"LocalRouter error (continuing to LLM): {e}")

    # ── special commands (pre-routing) ────────────────────────────

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
        _speak("Running system review. This may take a moment.")
        threading.Thread(
            target=lambda: (
                run_review_on_command(),
                _speak("Review complete. Check logs for suggestions."),
                update_feedback(row_id, True),
            ),
            daemon=True,
        ).start()
        return

    # ── OS agent commands (pre-routing) ──────────────────────────
    if any(k in lower for k in _OS_TRIGGER_KEYWORDS):
        row_id = log_command(transcribed_text, "OS_OPS")
        set_exec_state("RUNNING", transcribed_text[:60])
        _ui_log(f"OS_OPS: {transcribed_text[:80]}")
        _handle_os_ops(transcribed_text, row_id)
        return

    # ── focus mode commands (pre-routing) ────────────────────────
    if any(k in lower for k in ("enter deep focus", "deep focus mode", "focus mode", "start focus")):
        row_id = log_command(transcribed_text, "ENTER_FOCUS")
        threading.Thread(target=_activate_deep_focus, daemon=True).start()
        _speak("Deep Focus mode activated.")
        update_feedback(row_id, True)
        return

    if any(k in lower for k in ("standby", "exit focus", "stop focus", "leave focus", "deactivate focus")):
        row_id = log_command(transcribed_text, "EXIT_FOCUS")
        threading.Thread(target=_deactivate_deep_focus, daemon=True).start()
        _speak("Returning to normal mode.")
        update_feedback(row_id, True)
        return

    # ── normal intent routing ─────────────────────────────────────
    try:
        intent_label = _intent_router.route(transcribed_text)
    except (ConnectionError, TimeoutError) as e:
        _ui_log(f"Intent routing connection error — keyword fallback: {e}")
        _speak("API quota exceeded. Falling back to local keyword engine.")
        intent_label = _keyword_route_fallback(lower)
    except Exception as e:
        _ui_log(f"Intent routing failed — keyword fallback: {e}")
        if _is_api_error(e):
            _speak("API quota exceeded. Falling back to local keyword engine.")
        else:
            _speak("Routing failed. Using keyword engine.")
        intent_label = _keyword_route_fallback(lower)

    print(f"Intent: {intent_label}")
    _ui_log(f"Intent: {intent_label}")

    row_id = log_command(transcribed_text, intent_label)

    if intent_label == "ENTER_FOCUS":
        threading.Thread(target=_activate_deep_focus, daemon=True).start()
        _speak("Deep Focus mode activated.")
        update_feedback(row_id, True)
    elif intent_label == "EXIT_FOCUS":
        threading.Thread(target=_deactivate_deep_focus, daemon=True).start()
        _speak("Returning to normal mode.")
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
        _speak(f"Routing to {intent_label}")
        update_feedback(row_id, True)


# ── Listener subclass ─────────────────────────────────────────────────────────

class AfroListener(VoiceListener):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def _detection_loop(self):
        print("Listening for wake word...")
        while not self._shutdown:
            try:
                raw   = self.stream.read(FRAME_LENGTH, exception_on_overflow=False)
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


# ── GUI listener thread target ────────────────────────────────────────────────

def _on_gui_start() -> None:
    """Called from CockpitUI ACTIVATE button — runs in daemon thread."""
    global _listener
    _speak("Afro online. Say hey Jarvis to activate.")
    _listener = AfroListener(callback=on_wake_word_detected)
    try:
        _listener.start()
    except Exception as e:
        print(f"[Listener error] {e}")
        _ui_log(f"Listener error: {e}")


def _on_gui_stop() -> None:
    """Called from CockpitUI STANDBY button."""
    global _listener
    if _listener is not None:
        _listener._shutdown = True
        try:
            _listener._cleanup()
        except Exception:
            pass
    _ui_log("Listener stopped via GUI.")


# ── Shutdown ──────────────────────────────────────────────────────────────────

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


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global _listener, _qt_app, _cockpit, _bridge

    print("Project Afro Starting...")

    start_tray()
    print("System tray initialized.")

    start_dashboard()
    print("Dashboard running at http://127.0.0.1:5000")
    _ui_log("Afro system started.")

    start_meta_agent()
    print("Meta-agent scheduled (24h review cycle).")

    _watcher.start()
    print("Proactive watcher started.")

    _scheduler.run_loop()
    print("Scheduler agent started.")

    # Build app index in background (non-blocking)
    try:
        from agents.app_indexer import start_background_indexing
        start_background_indexing()
        print("App indexer started (background).")
    except Exception as e:
        print(f"[AppIndexer] Could not start: {e}")

    # ── GUI mode ──────────────────────────────────────────────────
    if _QT_AVAILABLE:
        try:
            _qt_app, _cockpit = launch_cockpit(
                on_start=lambda: threading.Thread(
                    target=_on_gui_start,
                    daemon=True,
                    name="AfroListener",
                ).start(),
                on_stop=_on_gui_stop,
            )

            _bridge = _UiBridge()
            _bridge.speaking_changed.connect(_cockpit.set_speaking)
            _bridge.log_message.connect(_cockpit.append_log)

            print("CockpitUI launched.")
            _ui_log("CockpitUI mode active.")

            try:
                sys.exit(_qt_app.exec())
            except SystemExit:
                pass
            finally:
                _shutdown_all(_listener)
            return
        except Exception as e:
            print(f"[CockpitUI] Launch failed ({e}) — falling back to headless mode.")

    # ── Headless fallback ─────────────────────────────────────────
    print("Initializing voice system (headless mode)...")
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
