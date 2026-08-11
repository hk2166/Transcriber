"""Voice-activity detection for MeetingMind.

Streaming Silero VAD (ONNX) plus a speech/silence segmenter that keeps
silence out of the transcription pipeline.
"""

from packages.vad.segmenter import SpeechSegment, SpeechSegmenter
from packages.vad.silero import SileroVAD

__all__ = ["SileroVAD", "SpeechSegment", "SpeechSegmenter"]
