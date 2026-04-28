import sys
import os
import struct
import time

import pyaudio
import pyttsx3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice.listener import VoiceListener
from voice.transcribe import process_speech
from core.intent_router import IntentRouter

SAMPLE_RATE = 16000
CAPTURE_SECONDS = 5
CHUNK = 1024

_tts_engine = pyttsx3.init()
_intent_router = IntentRouter()


def speak(text: str) -> None:
    _tts_engine.say(text)
    _tts_engine.runAndWait()


def capture_audio() -> bytes:
    audio = pyaudio.PyAudio()
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
            stream.stop_stream()
            stream.close()
        audio.terminate()

    return b"".join(frames)


def on_wake_word_detected() -> None:
    speak("Listening...")

    print("Capturing command...")
    audio_data = capture_audio()

    if not audio_data:
        print("[Warning] No audio captured.")
        return

    try:
        transcribed_text = process_speech(audio_data)
    except Exception as e:
        print(f"[Transcription error] {e}")
        return

    if not transcribed_text:
        print("[Warning] Empty transcription.")
        return

    print(f"User said: {transcribed_text}")

    intent_label = _intent_router.route(transcribed_text)
    print(f"Intent: {intent_label}")
    speak(f"Routing to {intent_label}")


class AfroListener(VoiceListener):
    """Extends VoiceListener to trigger a callback on wake-word detection."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

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
                    self._callback()
            except OSError as e:
                print(f"[Audio error] {e}")
                time.sleep(0.1)


def main() -> None:
    print("Project Afro Starting...")
    print("Initializing voice system...")

    listener = AfroListener(callback=on_wake_word_detected)

    try:
        listener.start()
    except KeyboardInterrupt:
        print("\n[Shutdown] KeyboardInterrupt received.")


if __name__ == "__main__":
    main()
