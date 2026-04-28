import os
import sys
import subprocess
import time

import numpy as np
import pyaudio

SAMPLE_RATE = 16000
FRAME_LENGTH = 1280  # openwakeword expects 80ms chunks at 16kHz
DEFAULT_MODEL = "alexa"
DETECTION_THRESHOLD = 0.5


def _get_model_dir() -> str:
    try:
        import openwakeword
        return os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    except ImportError:
        return ""


def _model_exists(model_name: str) -> bool:
    model_dir = _get_model_dir()
    if not model_dir or not os.path.isdir(model_dir):
        return False
    return any(
        f.lower().startswith(model_name.lower())
        for f in os.listdir(model_dir)
    )


def _download_model(model_name: str) -> bool:
    print(f"Wake word model not found. Downloading...")
    try:
        from openwakeword.utils import download_models
        download_models([model_name])
        return True
    except Exception:
        pass

    try:
        result = subprocess.run(
            [sys.executable, "-m", "openwakeword", "--download_models", model_name],
            timeout=120,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
        print(f"[openwakeword] Download stderr: {result.stderr.strip()}")
        return False
    except Exception as e:
        print(f"[openwakeword] Download failed: {e}")
        return False


class VoiceListener:
    def __init__(self, model_path: str = DEFAULT_MODEL):
        self.model_path = model_path
        self.oww_model = None
        self.audio = None
        self.stream = None

    def _resolve_model(self) -> bool:
        name = os.path.basename(self.model_path).split(".")[0]
        is_named = not os.path.isfile(self.model_path)

        if is_named and not _model_exists(name):
            ok = _download_model(name)
            if not ok or not _model_exists(name):
                print(f"[openwakeword] Model '{name}' unavailable after download attempt.")
                return False

        return True

    def _load_model(self):
        from openwakeword.model import Model

        if not self._resolve_model():
            raise RuntimeError(f"Model '{self.model_path}' could not be resolved.")

        self.oww_model = Model(
            wakeword_models=[self.model_path],
            inference_framework="onnx",
        )

    def _setup_stream(self):
        self.audio = pyaudio.PyAudio()
        self.stream = self.audio.open(
            rate=SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=FRAME_LENGTH,
        )

    def _detection_loop(self):
        print("Listening for wake word...")
        while True:
            try:
                raw = self.stream.read(FRAME_LENGTH, exception_on_overflow=False)
                frame = np.frombuffer(raw, dtype=np.int16)
                prediction = self.oww_model.predict(frame)

                for _model_name, score in prediction.items():
                    if score >= DETECTION_THRESHOLD:
                        print("\n=========================")
                        print("AFRO wake word detected")
                        print("=========================\n")
                        self.oww_model.reset()
                        break

            except OSError as e:
                print(f"[Audio error] {e}")
                time.sleep(0.1)

    def _cleanup(self):
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio is not None:
            self.audio.terminate()

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
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                print("\n[Shutdown] KeyboardInterrupt received.")
            return

        print("[Fallback] SpeechRecognition active. Speak freely — no wake word needed.\n")
        recognizer = sr.Recognizer()

        try:
            mic = sr.Microphone()
        except OSError as e:
            print(f"[Fallback] Microphone unavailable: {e}. Standing by.")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                print("\n[Shutdown] KeyboardInterrupt received.")
            return

        try:
            with mic as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
        except Exception as e:
            print(f"[Fallback] Ambient noise calibration failed: {e}")

        while True:
            try:
                with mic as source:
                    print("Listening...")
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                try:
                    text = recognizer.recognize_google(audio)
                    print(f"[Fallback detected] {text}")
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    print(f"[Fallback recognition error] {e}")
            except sr.WaitTimeoutError:
                pass
            except OSError as e:
                print(f"[Fallback microphone error] {e}")
                time.sleep(1)
            except KeyboardInterrupt:
                print("\n[Shutdown] KeyboardInterrupt received.")
                return

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
            print("\n[Shutdown] KeyboardInterrupt received.")
        finally:
            self._cleanup()


def start_wake_word_listener():
    listener = VoiceListener()
    listener.start()


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    start_wake_word_listener()
