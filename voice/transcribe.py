import sys
import numpy as np
import torch
from faster_whisper import WhisperModel

_model: WhisperModel | None = None
model_state: str = "RELEASED"


def _get_model() -> WhisperModel:
    global _model, model_state
    if _model is None:
        _model = WhisperModel(
            "base.en",
            device="cuda",
            compute_type="int8_float16",
        )
        model_state = "LOADED"
    return _model


def release_model() -> None:
    global _model, model_state
    _model = None
    model_state = "RELEASED"
    torch.cuda.empty_cache()


def _to_float32(audio_data) -> np.ndarray | None:
    if audio_data is None:
        return None

    if isinstance(audio_data, np.ndarray):
        waveform = audio_data.flatten().astype(np.float32)
    elif isinstance(audio_data, (bytes, bytearray)):
        if len(audio_data) == 0:
            return None
        waveform = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
    else:
        return None

    if waveform.size == 0:
        return None

    max_val = np.max(np.abs(waveform))
    if max_val > 1.0:
        waveform /= 32768.0

    return waveform


def process_speech(audio_data) -> str:
    waveform = _to_float32(audio_data)
    if waveform is None:
        return ""

    try:
        model = _get_model()
        segments, _ = model.transcribe(
            waveform,
            language="en",
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(segment.text for segment in segments).strip()
        return text
    except Exception as e:
        print(f"[Transcription error] {e}", file=sys.stderr)
        return ""
