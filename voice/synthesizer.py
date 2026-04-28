import io
import os
import sys
import threading
import tempfile
from datetime import datetime

import requests

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # default: Bella
REQUEST_TIMEOUT = 20

PERSONALITY_GREETINGS = {
    "MORNING":   "Good morning, let's get things moving.",
    "AFTERNOON": "Let's keep the momentum going.",
    "EVENING":   "Good evening, let's crush some code.",
    "NIGHT":     "Late grind, I like it.",
}


def _get_time_of_day() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "MORNING"
    if 12 <= hour < 17:
        return "AFTERNOON"
    if 17 <= hour < 21:
        return "EVENING"
    return "NIGHT"


class VoiceSynthesizer:

    def __init__(self):
        self._mode: str = "LOCAL"
        self._speed: float = 1.0
        self._muted: bool = False
        self._lock = threading.Lock()
        self._greeted: bool = False

        self._el_api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if self._el_api_key:
            self._mode = "CLOUD"

        self._local_engine = None
        self._init_local()

    def _init_local(self) -> None:
        try:
            import pyttsx3
            self._local_engine = pyttsx3.init()
        except Exception as e:
            print(f"[Synthesizer] pyttsx3 init failed: {e}", file=sys.stderr)

    def set_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode not in ("CLOUD", "LOCAL"):
            return
        if mode == "CLOUD" and not self._el_api_key:
            print("[Synthesizer] ELEVENLABS_API_KEY not set. Staying in LOCAL mode.")
            return
        with self._lock:
            self._mode = mode

    def set_speed(self, speech_speed: float) -> None:
        speed = max(0.5, min(2.0, float(speech_speed)))
        with self._lock:
            self._speed = speed
            if self._local_engine:
                try:
                    base_rate = 175
                    self._local_engine.setProperty("rate", int(base_rate * speed))
                except Exception:
                    pass

    def stop(self) -> None:
        """Best-effort interrupt of current playback (cloud or local)."""
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.stop()
        except Exception:
            pass
        if self._local_engine is not None:
            try:
                self._local_engine.stop()
            except Exception:
                pass

    def mute(self, is_muted: bool) -> None:
        with self._lock:
            self._muted = bool(is_muted)

    @property
    def is_muted(self) -> bool:
        return self._muted

    def _prepend_personality(self, text: str) -> str:
        tod = _get_time_of_day()
        if not self._greeted:
            greeting = PERSONALITY_GREETINGS.get(tod, "")
            self._greeted = True
            if greeting and not text.startswith(greeting):
                return f"{greeting} {text}"
        return text

    def _speak_cloud(self, text: str) -> None:
        try:
            url = f"{ELEVENLABS_API_URL}/{ELEVENLABS_VOICE_ID}"
            headers = {
                "xi-api-key": self._el_api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "text": text,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "speed": self._speed,
                },
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            audio_bytes = resp.content
            try:
                import pygame
                pygame.mixer.init()
                sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
                sound.play()
                while pygame.mixer.get_busy():
                    pygame.time.wait(50)
            except Exception:
                # fallback: write to temp file and play via OS
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(audio_bytes)
                    tmp_path = f.name
                if sys.platform == "win32":
                    os.startfile(tmp_path)
                else:
                    os.system(f"mpg123 -q '{tmp_path}' 2>/dev/null")

        except Exception as e:
            print(f"[Synthesizer] Cloud TTS failed: {e}. Falling back to local.", file=sys.stderr)
            self._speak_local(text)

    def _speak_local(self, text: str) -> None:
        if self._local_engine is None:
            print(f"[Synthesizer] {text}")
            return
        try:
            self._local_engine.say(text)
            self._local_engine.runAndWait()
        except Exception as e:
            print(f"[Synthesizer] Local TTS error: {e}", file=sys.stderr)
            print(f"[Synthesizer] {text}")

    def speak(self, text_to_speak: str) -> None:
        if not text_to_speak or not text_to_speak.strip():
            return
        with self._lock:
            if self._muted:
                print(f"[Synthesizer/muted] {text_to_speak}")
                return
            mode = self._mode

        text = self._prepend_personality(text_to_speak)

        if mode == "CLOUD":
            self._speak_cloud(text)
        else:
            self._speak_local(text)

    def speak_async(self, text_to_speak: str) -> None:
        threading.Thread(
            target=self.speak,
            args=(text_to_speak,),
            daemon=True,
        ).start()
