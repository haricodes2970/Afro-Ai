import sys
import os
import time

import numpy as np
import pyaudio
import pyttsx3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from voice.listener import VoiceListener, FRAME_LENGTH, DETECTION_THRESHOLD
from voice.transcribe import process_speech
from core.intent_router import IntentRouter
from core.system_tray import start_tray
from agents.process_agent import ProcessAgent

SAMPLE_RATE = 16000
CAPTURE_SECONDS = 5
CHUNK = 1024

_tts_engine = pyttsx3.init()
_intent_router = IntentRouter()

PROCESS_OP_KEYWORDS = {
    "status": "STATUS",
    "kill": "KILL",
    "terminate": "KILL",
    "stop": "KILL",
    "optimize": "OPTIMIZE",
    "clean up": "OPTIMIZE",
    "cleanup": "OPTIMIZE",
}


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


def _handle_process_ops(transcribed_text: str) -> None:
    agent = ProcessAgent()
    op, process_name = _extract_process_op(transcribed_text)

    if op == "STATUS":
        agent.status()
        speak("Here are the top running processes.")

    elif op == "KILL":
        if not process_name:
            speak("Please specify a process name to kill.")
            return
        freed_mb = agent.kill(process_name)
        if freed_mb > 0:
            speak(f"Process terminated. Freed {freed_mb:.0f} MB RAM")
        else:
            speak(f"Could not find process {process_name}")

    elif op == "OPTIMIZE":
        freed_mb = agent.optimize()
        if freed_mb > 0:
            speak(f"Optimization complete. Freed {freed_mb:.0f} MB RAM")
        else:
            speak("No bloatware processes found running.")


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

    if intent_label == "PROCESS_OPS":
        _handle_process_ops(transcribed_text)
    else:
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
                raw = self.stream.read(FRAME_LENGTH, exception_on_overflow=False)
                frame = np.frombuffer(raw, dtype=np.int16)
                prediction = self.oww_model.predict(frame)

                for model_name, score in prediction.items():
                    if score >= DETECTION_THRESHOLD:
                        print("\n=========================")
                        print("AFRO IS ACTIVE")
                        print("=========================\n")
                        self.oww_model.reset()
                        self._callback()
                        break

            except OSError as e:
                print(f"[Audio error] {e}")
                time.sleep(0.1)


def main() -> None:
    print("Project Afro Starting...")

    start_tray()
    print("System tray initialized.")

    print("Initializing voice system...")
    listener = AfroListener(callback=on_wake_word_detected)

    try:
        listener.start()
    except KeyboardInterrupt:
        print("\n[Shutdown] KeyboardInterrupt received.")


if __name__ == "__main__":
    main()
