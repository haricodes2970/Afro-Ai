import io
import os
import sys
import subprocess
import time
import contextlib
import threading

import numpy as np
import pyaudio

SAMPLE_RATE         = 16000
FRAME_LENGTH        = 1280          # 80ms at 16kHz
DEFAULT_MODEL       = "hey_jarvis"
MODEL_FILE          = "hey_jarvis_v0.1.onnx"
DETECTION_THRESHOLD = 0.5           # sensitivity in ACTIVE mode

# ── Idle mode tunables ───────────────────────────────────────────────────────
IDLE_TIMEOUT_S      = 30.0          # seconds of silence before entering IDLE
IDLE_THRESHOLD      = 0.65          # stricter threshold in IDLE (fewer false positives)
IDLE_SLEEP_S        = 0.04          # extra sleep per frame in IDLE (~25 frames/sec)
ACTIVE_SLEEP_S      = 0.0           # no extra sleep in ACTIVE (full throughput)

# Listener state exposed for tray / dashboard
_listener_state     = "IDLE"        # "ACTIVE" | "IDLE"
_listener_state_lock = threading.Lock()


def get_listener_state() -> str:
    with _listener_state_lock:
        return _listener_state


def _set_listener_state(state: str) -> None:
    global _listener_state
    with _listener_state_lock:
        _listener_state = state
    # Non-blocking best-effort tray update
    try:
        from core.tray_icon import set_tray_state
        set_tray_state(state)
    except Exception:
        pass


def _get_model_dir() -> str:
    try:
        import openwakeword
        return os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    except ImportError:
        return ""


def _model_exists() -> bool:
    model_dir = _get_model_dir()
    if not model_dir or not os.path.isdir(model_dir):
        return False
    target = MODEL_FILE.lower()
    return any(f.lower() == target for f in os.listdir(model_dir))


def _download_model() -> bool:
    print("hey_jarvis model missing. Downloading...")
    # Primary: openwakeword Python API
    try:
        from openwakeword.utils import download_models
        download_models([DEFAULT_MODEL])
        if _model_exists():
            return True
    except Exception:
        pass

    # Secondary: openwakeword.download CLI
    try:
        result = subprocess.run(
            [sys.executable, "-m", "openwakeword.download", "--models", DEFAULT_MODEL],
            timeout=120,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and _model_exists():
            return True
        if result.stderr.strip():
            print(f"[openwakeword] Download stderr: {result.stderr.strip()}")
    except Exception as e:
        print(f"[openwakeword] Download failed: {e}")

    # Tertiary: legacy CLI flag
    try:
        result = subprocess.run(
            [sys.executable, "-m", "openwakeword", "--download_models", DEFAULT_MODEL],
            timeout=120,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and _model_exists():
            return True
    except Exception:
        pass

    return False


class VoiceListener:
    def __init__(self, model_path: str = DEFAULT_MODEL):
        self.model_path = model_path
        self.oww_model  = None
        self.audio      = None
        self.stream     = None
        self._shutdown  = False

        # Idle mode state
        self._mode            = "IDLE"   # "ACTIVE" | "IDLE"
        self._last_detected   = 0.0      # epoch timestamp of last detection
        self._mode_lock       = threading.Lock()

    # ── Mode management ─────────────────────────────────────────────────────

    def _enter_active(self) -> None:
        with self._mode_lock:
            if self._mode == "ACTIVE":
                return
            self._mode = "ACTIVE"
        print("[Listener] State → ACTIVE (full sensitivity)")
        _set_listener_state("ACTIVE")

    def _enter_idle(self) -> None:
        with self._mode_lock:
            if self._mode == "IDLE":
                return
            self._mode = "IDLE"
        print("[Listener] State → IDLE (reduced polling)")
        _set_listener_state("IDLE")

    def _current_threshold(self) -> float:
        with self._mode_lock:
            return IDLE_THRESHOLD if self._mode == "IDLE" else DETECTION_THRESHOLD

    def _current_sleep(self) -> float:
        with self._mode_lock:
            return IDLE_SLEEP_S if self._mode == "IDLE" else ACTIVE_SLEEP_S

    # ── Model / stream setup ─────────────────────────────────────────────────

    def _resolve_model(self) -> bool:
        if not _model_exists():
            ok = _download_model()
            if not ok or not _model_exists():
                print(f"[openwakeword] '{MODEL_FILE}' unavailable after download attempt.")
                return False
        return True

    def _load_model(self):
        from openwakeword.model import Model

        if not self._resolve_model():
            raise RuntimeError(f"Model '{MODEL_FILE}' could not be resolved.")

        self.oww_model = Model(
            wakeword_models=[self.model_path],
            inference_framework="onnx",
        )

    def _setup_stream(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.audio = pyaudio.PyAudio()
        self.stream = self.audio.open(
            rate=SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=FRAME_LENGTH,
        )

    # ── Detection loop ───────────────────────────────────────────────────────

    def _detection_loop(self):
        print("Listening for wake word...")
        self._last_detected = time.monotonic()

        while not self._shutdown:
            # Idle transition check — before the read so we don't block
            elapsed = time.monotonic() - self._last_detected
            if elapsed >= IDLE_TIMEOUT_S:
                self._enter_idle()
            else:
                self._enter_active()

            try:
                raw   = self.stream.read(FRAME_LENGTH, exception_on_overflow=False)
                frame = np.frombuffer(raw, dtype=np.int16)
                prediction = self.oww_model.predict(frame)

                threshold = self._current_threshold()
                detected  = False

                for _model_name, score in prediction.items():
                    if score >= threshold:
                        detected = True
                        break

                if detected:
                    # Instantly restore ACTIVE regardless of current mode
                    self._last_detected = time.monotonic()
                    self._enter_active()
                    print("\n=========================")
                    print("AFRO IS ACTIVE")
                    print("=========================\n")
                    self.oww_model.reset()

                # Throttle in IDLE to reduce CPU load
                extra_sleep = self._current_sleep()
                if extra_sleep > 0:
                    time.sleep(extra_sleep)

            except OSError as e:
                if self._shutdown:
                    break
                print(f"[Audio error] {e}")
                time.sleep(0.1)

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def _cleanup(self):
        self._shutdown = True
        if self.stream is not None:
            try:
                self.stream.stop_stream()
            except Exception:
                pass
            try:
                self.stream.close()
            except Exception:
                pass
        if self.audio is not None:
            try:
                self.audio.terminate()
            except Exception:
                pass

    # ── Fallback (no openwakeword) ───────────────────────────────────────────

    def _fallback_mode(self, reason: str = ""):
        if reason:
            print(f"\n[Voice disabled] {reason}")

        try:
            import speech_recognition as sr
        except ImportError:
            print(
                "\nSpeechRecognition not installed. Setup Required:\n"
                "  pip install SpeechRecognition pyaudio"
            )
            print("[Fallback] No recognition engine available. Standing by. Press Ctrl+C to exit.")
            try:
                while not self._shutdown:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            return

        print("[Fallback] SpeechRecognition active. Speak freely — no wake word needed.\n")
        recognizer = sr.Recognizer()

        try:
            mic = sr.Microphone()
        except OSError as e:
            print(f"[Fallback] Microphone unavailable: {e}. Standing by.")
            try:
                while not self._shutdown:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            return

        try:
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception as e:
            print(f"[Fallback] Ambient noise calibration failed: {e}")

        while not self._shutdown:
            try:
                with mic as source:
                    print("Listening...")
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                try:
                    text = recognizer.recognize_google(audio)
                    print(f"[Fallback detected] {text}")
                    self._last_detected = time.monotonic()
                    self._enter_active()
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    print(f"[Fallback recognition error] {e}")
            except sr.WaitTimeoutError:
                pass
            except OSError as e:
                if not self._shutdown:
                    print(f"[Fallback microphone error] {e}")
                time.sleep(1)
            except KeyboardInterrupt:
                break

    # ── Public entry point ───────────────────────────────────────────────────

    def start(self):
        try:
            self._load_model()
        except Exception as e:
            print(f"[openwakeword] Model load failed: {e}")
            self._fallback_mode("Wake-word model could not be loaded.")
            return

        try:
            self._setup_stream()
        except OSError as e:
            print(f"[Microphone setup error] {e}")
            self._cleanup()
            return

        try:
            self._detection_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()


def start_wake_word_listener():
    listener = VoiceListener()
    listener.start()


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    start_wake_word_listener()
