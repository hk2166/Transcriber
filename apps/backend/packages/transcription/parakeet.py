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
    #: Encoder memory grows super-linearly with clip length (measured: a
    #: 3-minute clip exceeds 7 GB). Anything longer is windowed.
    MAX_CLIP_SECONDS = 30

    def __init__(self, variant: str = "parakeet-v3", quantization: str = "int8") -> None:
        import onnx_asr

        model_id = PARAKEET_MODELS.get(variant, PARAKEET_MODELS["parakeet-v3"])
        self.variant = variant
        # v3 is multilingual; we don't run language ID, so report "multi".
        self.language = "en" if variant == "parakeet-v2" else "multi"
        # CPU provider, explicitly. onnx_asr defaults to every available
        # provider, which on macOS puts CoreML first — and ORT's CoreML EP
        # re-compiles per input shape and never releases: measured on an M-series
        # Mac, memory ratcheted 1.4 → 7+ GB across a dozen segment lengths (even
        # identical 30 s inputs grew 3.6 → 6.5 GB), which is what OOM-crashed
        # long meetings. On CPU the same sequence stays flat at ~1.8 GB and each
        # call is 5–20× faster (0.1–0.7 s vs 2.2–3.4 s).
        self.model = onnx_asr.load_model(
            model_id, quantization=quantization, providers=["CPUExecutionProvider"]
        )
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
        # Window long clips and join the text — never hand the encoder more
        # than MAX_CLIP_SECONDS at once (defense in depth behind the VAD cap).
        max_samples = self.MAX_CLIP_SECONDS * self.SAMPLE_RATE
        pieces = []
        for start in range(0, samples.size, max_samples):
            chunk = samples[start : start + max_samples]
            piece = (self.model.recognize(chunk, sample_rate=self.SAMPLE_RATE) or "").strip()
            if piece:
                pieces.append(piece)
        text = " ".join(pieces)
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
