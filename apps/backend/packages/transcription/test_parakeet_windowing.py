"""Parakeet never sees more than MAX_CLIP_SECONDS at once (memory guard)."""

import numpy as np

from packages.transcription.parakeet import ParakeetTranscriber


class _FakeModel:
    def __init__(self):
        self.calls: list[int] = []

    def recognize(self, samples, sample_rate):
        self.calls.append(samples.size)
        return f"piece{len(self.calls)}"


def _transcriber() -> ParakeetTranscriber:
    t = object.__new__(ParakeetTranscriber)  # skip the ONNX model load
    t.language = "en"
    t.model = _FakeModel()
    return t


def test_long_clip_is_windowed_and_text_joined():
    t = _transcriber()
    sr = ParakeetTranscriber.SAMPLE_RATE
    seg = t.transcribe(np.zeros(70 * sr, np.float32), start_ms=5000)

    assert t.model.calls == [30 * sr, 30 * sr, 10 * sr]  # 30 + 30 + 10 s
    assert seg.text == "piece1 piece2 piece3"
    assert (seg.start_ms, seg.end_ms) == (5000, 75000)  # timing spans the whole clip


def test_short_clip_is_a_single_call():
    t = _transcriber()
    sr = ParakeetTranscriber.SAMPLE_RATE
    t.transcribe(np.zeros(10 * sr, np.float32))
    assert t.model.calls == [10 * sr]


def test_all_silent_windows_return_none():
    t = _transcriber()
    t.model.recognize = lambda samples, sample_rate: ""
    assert t.transcribe(np.zeros(45 * ParakeetTranscriber.SAMPLE_RATE, np.float32)) is None


def test_model_is_loaded_on_the_cpu_provider(monkeypatch):
    # The CoreML provider ratchets memory per input shape (measured); the
    # constructor must pin CPU explicitly rather than take onnx_asr's default.
    import onnx_asr

    captured = {}

    def fake_load_model(model_id, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(onnx_asr, "load_model", fake_load_model)
    ParakeetTranscriber(variant="parakeet-v2")
    assert captured["providers"] == ["CPUExecutionProvider"]
