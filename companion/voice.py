"""Microphone capture + speech-to-text for the companion.

Records from the default mic until a short silence (or a max duration), then
transcribes with the offline ``stt`` engine. No TTS — the slime listens but
speaks only in text bubbles.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

SAMPLE_RATE = 16000


def available() -> bool:
    try:
        import sounddevice  # noqa: F401
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def record(max_seconds: float = 12.0, silence_seconds: float = 1.6) -> Optional["object"]:
    """Record mono float32 audio, auto-stopping after a silence. Returns array or None."""
    import numpy as np
    import sounddevice as sd

    block = int(SAMPLE_RATE * 0.1)  # 100ms blocks
    max_blocks = int(max_seconds / 0.1)
    silence_blocks = int(silence_seconds / 0.1)

    captured: list = []
    quiet = 0
    heard = False
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=block) as stream:
            for _ in range(max_blocks):
                data, _overflow = stream.read(block)
                chunk = data.reshape(-1)
                captured.append(chunk.copy())
                level = float(np.abs(chunk).mean())
                if level > 0.01:
                    heard = True
                    quiet = 0
                elif heard:
                    quiet += 1
                    if quiet >= silence_blocks:
                        break
    except Exception:
        return None

    if not captured:
        return None
    audio = np.concatenate(captured)
    if not heard or float(np.abs(audio).max()) < 0.01:
        return None
    return audio


def transcribe_array(audio) -> str:
    """Transcribe a float32 numpy array to text."""
    import soundfile as sf

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, audio, SAMPLE_RATE)
        tmp = f.name
    try:
        from stt import transcribe
        return (transcribe(tmp) or "").strip()
    finally:
        Path(tmp).unlink(missing_ok=True)


def listen() -> Optional[str]:
    """Record then transcribe. Returns recognised text, or None if nothing heard."""
    audio = record()
    if audio is None:
        return None
    text = transcribe_array(audio)
    return text or None
