import os
import sys
import struct
import time

import pyaudio
from dotenv import load_dotenv

load_dotenv()


ACCESS_KEY_PLACEHOLDERS = {
    "your_access_key_here",
    "your-picovoice-access-key",
    "your_picovoice_access_key",
    "paste_your_picovoice_access_key_here",
    "replace_me",
}


class VoiceListener:
    def __init__(self):
        self.porcupine = None
        self.audio = None
        self.stream = None
        self.access_key = os.getenv("PICOVOICE_ACCESS_KEY", "").strip()
        self.wake_engine_status: str = "FALLBACK"

    def _has_configured_access_key(self) -> bool:
        if not self.access_key:
            return False
        return self.access_key.lower() not in ACCESS_KEY_PLACEHOLDERS

    def _setup_porcupine(self):
        import pvporcupine

        try:
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=["porcupine"],
            )
            self.wake_engine_status = "ACTIVE"
        except pvporcupine.PorcupineInvalidArgumentError as e:
            print(f"[Porcupine] Invalid argument: {e}")
            print("Porcupine initialization failed. Switching to fallback mode.")
            self.wake_engine_status = "FALLBACK"
            raise
        except Exception as e:
            print(f"[Porcupine] Initialization error: {e}")
            print("Porcupine initialization failed. Switching to fallback mode.")
            self.wake_engine_status = "FALLBACK"
            raise

    def _setup_stream(self):
        self.audio = pyaudio.PyAudio()
        self.stream = self.audio.open(
            rate=self.porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.porcupine.frame_length,
        )

    def _detection_loop(self):
        print("Listening for wake word...")
        while True:
            try:
                raw = self.stream.read(
                    self.porcupine.frame_length, exception_on_overflow=False
                )
                frame = struct.unpack_from("h" * self.porcupine.frame_length, raw)
                result = self.porcupine.process(frame)
                if result >= 0:
                    print("\n=========================")
                    print("AFRO LISTENING ACTIVATED")
                    print("=========================\n")
            except OSError as e:
                print(f"[Audio error] {e}")
                time.sleep(0.1)

    def _cleanup(self):
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio is not None:
            self.audio.terminate()
        if self.porcupine is not None:
            self.porcupine.delete()

    def _fallback_mode(self, reason: str = ""):
        if reason:
            print(f"\n[Voice disabled] {reason}")
        print("Set PICOVOICE_ACCESS_KEY in .env to enable wake-word detection.")
        print("Get one at: https://console.picovoice.ai/")

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
        if not self._has_configured_access_key():
            self._fallback_mode("Picovoice AccessKey is missing or still a placeholder.")
            return

        try:
            self._setup_porcupine()
        except Exception:
            self._fallback_mode("Wake-word detection could not initialize.")
            return

        try:
            self._setup_stream()
            self._detection_loop()
        except KeyboardInterrupt:
            print("\n[Shutdown] KeyboardInterrupt received.")
        except OSError as e:
            print(f"[Microphone setup error] {e}")
        finally:
            self._cleanup()


def start_wake_word_listener():
    listener = VoiceListener()
    listener.start()


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    start_wake_word_listener()
