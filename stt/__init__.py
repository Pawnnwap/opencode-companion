"""stt - Offline Chinese speech-to-text using Paraformer-zh via sherpa-onnx.

Usage::

    from stt import transcribe

    # From file
    text = transcribe("audio.wav")

    # From raw audio
    text = transcribe(audio_array, stream=False)
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np

from ._engine import STTEngine

__all__ = ["transcribe"]

_engine: STTEngine | None = None


def _get_engine() -> STTEngine:
    global _engine
    if _engine is None:
        _engine = STTEngine()
    return _engine


def transcribe(
    audio: Union[str, Path, np.ndarray],
    stream: bool = False,
) -> str:
    """Transcribe Chinese speech to text.

    Args:
        audio: WAV file path (str/Path) or numpy float32 array.
        stream: If False, batch-transcribe the full audio at once (fastest).
                If True, use streaming recognition (lower latency for real-time).

    Returns:
        Transcribed Chinese text.
    """
    engine = _get_engine()

    if isinstance(audio, (str, Path)):
        return engine.transcribe_file(audio, stream=stream)
    else:
        return engine.transcribe_audio(
            np.asarray(audio, dtype=np.float32), stream=stream
        )
