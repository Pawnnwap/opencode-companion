"""Core STT engine wrapping sherpa-onnx Paraformer-zh."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

try:
    from sherpa_onnx.offline_recognizer import OfflineRecognizer
except ImportError:
    raise ImportError("sherpa-onnx is required: pip install sherpa-onnx")

from ._download import MODEL_DIR, download_models


class STTEngine:
    def __init__(
        self,
        model_dir: Optional[str | Path] = None,
        num_threads: int = 4,
        auto_download: bool = True,
    ):
        if model_dir is None:
            if auto_download:
                download_models()
            model_dir = MODEL_DIR
        else:
            model_dir = Path(model_dir)

        model_path = model_dir / "model.int8.onnx"
        tokens_path = model_dir / "tokens.txt"

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found: {model_path}\nRun 'python -m stt._download' to download."
            )

        self._recognizer = OfflineRecognizer.from_paraformer(
            paraformer=str(model_path),
            tokens=str(tokens_path),
            num_threads=num_threads,
        )
        self._sample_rate = 16000

    def transcribe_file(self, audio_path: str | Path, stream: bool = False) -> str:
        import soundfile as sf

        audio, sr = sf.read(str(audio_path), dtype="float32")
        if sr != self._sample_rate:
            audio = self._resample(audio, sr, self._sample_rate)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return self.transcribe_audio(audio, stream=stream)

    def transcribe_audio(self, audio: np.ndarray, stream: bool = False) -> str:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        s = self._recognizer.create_stream()
        s.accept_waveform(self._sample_rate, audio.tolist())

        if stream:
            self._recognizer.decode_stream(s)
        else:
            self._recognizer.decode_stream(s)

        return s.result.text

    @staticmethod
    def _resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        if orig_sr == target_sr:
            return audio
        duration = len(audio) / orig_sr
        new_length = int(duration * target_sr)
        indices = np.linspace(0, len(audio) - 1, new_length)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)
