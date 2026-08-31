"""Engine catalog + factory routing (no model loads)."""

from packages.transcription import ASR_ENGINES, engines, parakeet, transcriber


def test_catalog_has_expected_engines():
    ids = {e.id for e in ASR_ENGINES}
    assert {"whisper-small", "parakeet-v2", "parakeet-v3"} <= ids
    # every spec is fully described for the UI
    for spec in ASR_ENGINES:
        assert spec.label and spec.note and spec.languages and spec.size_mb > 0
        assert spec.family in ("whisper", "parakeet")


def test_factory_routes_whisper_size(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        transcriber, "WhisperTranscriber", lambda model_size: captured.setdefault("size", model_size)
    )
    engines.make_transcriber("whisper-medium")
    assert captured["size"] == "medium"


def test_factory_routes_parakeet_variant(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        parakeet, "ParakeetTranscriber", lambda variant: captured.setdefault("variant", variant)
    )
    engines.make_transcriber("parakeet-v2")
    assert captured["variant"] == "parakeet-v2"


def test_parakeet_model_ids():
    assert parakeet.PARAKEET_MODELS["parakeet-v2"] == "nemo-parakeet-tdt-0.6b-v2"
    assert parakeet.PARAKEET_MODELS["parakeet-v3"] == "nemo-parakeet-tdt-0.6b-v3"
