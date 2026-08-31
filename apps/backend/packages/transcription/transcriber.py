"""Whisper transcription — turns speech-segment audio into text.

Wraps faster-whisper (CTranslate2, no torch) with the model loaded once and
reused. Built for the live path: greedy decoding, no cross-segment
conditioning, and VAD already handled upstream — so each call is independent
and fast.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

__all__ = ["TranscriptSegment", "WhisperTranscriber"]


@dataclass
class TranscriptSegment:
    """A transcribed span of speech.

    Attributes:
        text: The recognised text.
        start_ms: Segment start relative to stream start, in milliseconds.
        end_ms: Segment end relative to stream start, in milliseconds.
        language: Detected (or configured) language code, e.g. ``"en"``.
        confidence: 0..1, ``exp(mean avg_logprob)`` — higher is more certain.
    """

    text: str
    start_ms: int
    end_ms: int
    language: str
    confidence: float


class WhisperTranscriber:
    """faster-whisper wrapper, model loaded once and reused.

    The model is CPU int8 by default (``device="auto"`` resolves to CPU on
    Apple Silicon, since CTranslate2 has no Metal backend). Loading takes a
    few seconds, so create one instance and share it.

    Decoding is tuned for live use: ``beam_size=1`` (greedy, fastest) and
    ``condition_on_previous_text=False`` so an earlier segment can't bias or
    hallucinate into a later one.
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        language: str | None = None,
        beam_size: int = 1,
        no_speech_threshold: float = 0.6,
        min_language_prob: float = 0.6,
        min_avg_logprob: float = -1.0,
    ) -> None:
        """Load the Whisper model.

        Args:
            model_size: faster-whisper model name (``"base"``, ``"small"``,
                ``"medium"``, ...).
            device: ``"auto"``, ``"cpu"``, or ``"cuda"``.
            compute_type: e.g. ``"int8"`` (CPU) or ``"float16"`` (GPU).
            language: Force a language code, or ``None`` to auto-detect.
            beam_size: Beam width; 1 is greedy and fastest.
            no_speech_threshold: Drop sub-segments Whisper marks as non-speech
                above this probability (hallucination guard).
            min_language_prob: When auto-detecting, reject the whole clip if
                the detected language's confidence is below this — noise and
                silence detect obscure languages with low confidence.
            min_avg_logprob: Drop sub-segments whose average log-probability is
                below this (garbled output).
        """
        self.language = language
        self.beam_size = beam_size
        self.no_speech_threshold = no_speech_threshold
        self.min_language_prob = min_language_prob
        self.min_avg_logprob = min_avg_logprob
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info(
            "WhisperTranscriber loaded (model=%s, compute=%s, language=%s).",
            model_size,
            compute_type,
            language or "auto",
        )

    def transcribe_file(self, path: str) -> list[TranscriptSegment]:
        """Re-transcribe a whole recording for the post-meeting refine pass.

        Unlike the live path (independent VAD clips, greedy decoding, no
        cross-segment conditioning), this feeds the *entire* audio at once with
        beam search, cross-segment context, and faster-whisper's own VAD — so
        punctuation, casing, and boundary words come out markedly better. Slow;
        run in a worker thread post-meeting.
        """
        segments, info = self.model.transcribe(
            path,
            language=self.language,
            beam_size=max(self.beam_size, 5),
            condition_on_previous_text=True,
            vad_filter=True,
        )
        out: list[TranscriptSegment] = []
        for s in segments:
            text = s.text.strip()
            if not text or s.no_speech_prob >= self.no_speech_threshold:
                continue
            out.append(
                TranscriptSegment(
                    text=text,
                    start_ms=int(s.start * 1000),
                    end_ms=int(s.end * 1000),
                    language=info.language,
                    confidence=min(1.0, float(np.exp(s.avg_logprob))),
                )
            )
        return out

    def transcribe(
        self, audio: np.ndarray, start_ms: int = 0
    ) -> TranscriptSegment | None:
        """Transcribe one speech clip.

        Args:
            audio: 1-D or ``(N, 1)`` float32 audio in [-1, 1] at 16 kHz.
            start_ms: Stream-relative offset of the clip, added to the
                returned timestamps.

        Returns:
            A :class:`TranscriptSegment`, or ``None`` if no speech was
            recognised (e.g. silence Whisper declined to transcribe).
        """
        samples = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).reshape(-1))
        segments, info = self.model.transcribe(
            samples,
            language=self.language,
            beam_size=self.beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        # Auto-detected language with low confidence ⇒ almost always noise the
        # VAD let through; Whisper would hallucinate text in a random language.
        if self.language is None and info.language_probability < self.min_language_prob:
            return None

        subs = [
            s
            for s in segments
            if s.text.strip()
            and s.no_speech_prob < self.no_speech_threshold
            and s.avg_logprob > self.min_avg_logprob
        ]
        if not subs:
            return None

        text = " ".join(s.text.strip() for s in subs)
        avg_logprob = sum(s.avg_logprob for s in subs) / len(subs)
        confidence = min(1.0, float(np.exp(avg_logprob)))
        return TranscriptSegment(
            text=text,
            start_ms=start_ms + int(subs[0].start * 1000),
            end_ms=start_ms + int(subs[-1].end * 1000),
            language=info.language,
            confidence=confidence,
        )