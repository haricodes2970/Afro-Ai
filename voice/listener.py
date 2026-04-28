import os
import sys
import struct
import time

import pyaudio
from dotenv import load_dotenv

load_dotenv()


class VoiceListener:
    def __init__(self):
        self.porcupine = None
        self.audio = None
        self.stream = None
        self.access_key = os.getenv("PICOVOICE_ACCESS_KEY", "").strip()

    def _setup_porcupine(self):
        import pvporcupine
        self.porcupine = pvporcupine.create(
            access_key=self.access_key,
            keywords=["porcupine"],
        )

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

    def _fallback_mode(self):
        import speech_recognition as sr

        print("\nPicovoice AccessKey not found.")
        print("Get one at: https://console.picovoice.ai/")
        print("\n[Fallback] Starting basic speech recognition loop...\n")

        recognizer = sr.Recognizer()
        mic = sr.Microphone()

        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)

        while True:
            try:
                with mic as source:
                    print("Listening...")
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                try:
                    text = recognizer.recognize_google(audio)
                    print(f"[Detected] {text}")
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    print(f"[Recognition error] {e}")
            except sr.WaitTimeoutError:
                pass
            except OSError as e:
                print(f"[Microphone error] {e}")
                time.sleep(1)

    def start(self):
        if not self.access_key:
            self._fallback_mode()
            return

        try:
            self._setup_porcupine()
        except Exception as e:
            print(f"[Porcupine init failed] {e}")
            print("\nPicovoice AccessKey not found.")
            print("Get one at: https://console.picovoice.ai/")
            self._fallback_mode()
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
