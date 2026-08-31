"""NVIDIA Parakeet-TDT transcription via onnx-asr.

Torch-free: runs on the same onnxruntime Confab already bundles for VAD and
embeddings. Parakeet tops the Open ASR leaderboard on English (beating
Whisper-large-v3) and, being a transducer, doesn't hallucinate phantom text on
near-silence the way Whisper can. v2 is English-only; v3 covers 25 (mostly
European) languages. The int8 model (~670 MB) downloads from Hugging Face on
first use, like Whisper's.

Same interface as :class:`WhisperTranscriber`: ``transcribe(audio, start_ms)``.
"""

from __future__ import annotations

import logging

import numpy as np

from packages.transcription.transcriber import TranscriptSegment

logger = logging.getLogger(__name__)

__all__ = ["PARAKEET_MODELS", "ParakeetTranscriber"]

#: Engine id → onnx-asr model id.
PARAKEET_MODELS = {
    "parakeet-v2": "nemo-parakeet-tdt-0.6b-v2",  # English only
    "parakeet-v3": "nemo-parakeet-tdt-0.6b-v3",  # 25 languages
}


class ParakeetTranscriber:
    """onnx-asr Parakeet wrapper, model loaded once and reused.

    ``onnx_asr`` is imported lazily so this module stays cheap to import; the
    model (and its int8 weights) load on construction, which takes a few
    seconds — build one instance and share it.
    """

    SAMPLE_RATE = 16_000

    def __init__(self, variant: str = "parakeet-v3", quantization: str = "int8") -> None:
        import onnx_asr

        model_id = PARAKEET_MODELS.get(variant, PARAKEET_MODELS["parakeet-v3"])
        self.variant = variant
        # v3 is multilingual; we don't run language ID, so report "multi".
        self.language = "en" if variant == "parakeet-v2" else "multi"
        self.model = onnx_asr.load_model(model_id, quantization=quantization)
        logger.info("ParakeetTranscriber loaded (%s, %s).", model_id, quantization)

    def transcribe(
        self, audio: np.ndarray, start_ms: int = 0
    ) -> TranscriptSegment | None:
        """Transcribe one VAD-segmented speech clip.

        Args:
            audio: 1-D or ``(N, 1)`` float32 audio in [-1, 1] at 16 kHz.
            start_ms: Stream-relative offset, added to the returned timestamps.

        Returns:
            A :class:`TranscriptSegment`, or ``None`` if nothing was recognised.
        """
        samples = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))
        if samples.size == 0:
            return None
        text = (self.model.recognize(samples, sample_rate=self.SAMPLE_RATE) or "").strip()
        if not text:
            return None
        duration_ms = int(samples.size / self.SAMPLE_RATE * 1000)
        return TranscriptSegment(
            text=text,
            start_ms=start_ms,
            end_ms=start_ms + duration_ms,
            language=self.language,
            # onnx-asr doesn't surface token-level log-probs; the VAD already
            # gated silence, so treat a returned transcript as confident.
            confidence=1.0,
        )
