"""Smoke tests for SileroVAD using the bundled ONNX model.

These load the real model (shipped with faster-whisper) but need no audio
fixtures — silence is generated in-process.
"""

import numpy as np

from packages.vad.silero import SileroVAD

BLOCK = 1024


def test_silence_is_not_speech():
    vad = SileroVAD()
    confidences = [vad.confidence(np.zeros((BLOCK, 1), np.float32)) for _ in range(16)]
    assert max(confidences) < 0.5
    assert not any(vad.is_speech(np.zeros((BLOCK, 1), np.float32)) for _ in range(4))


def test_handles_odd_length_chunks_by_buffering():
    vad = SileroVAD()
    # 1500 samples = two 512 windows + 476 buffered.
    vad.confidence(np.zeros((1500, 1), np.float32))
    assert vad._buffer.size == 476
    # 476 + 1500 = 1976 = three windows + 440 buffered.
    vad.confidence(np.zeros((1500, 1), np.float32))
    assert vad._buffer.size == 440


def test_reset_clears_buffer_and_state():
    vad = SileroVAD()
    vad.confidence(np.zeros((1500, 1), np.float32))
    vad.reset()
    assert vad._buffer.size == 0
    assert vad._last_prob == 0.0
