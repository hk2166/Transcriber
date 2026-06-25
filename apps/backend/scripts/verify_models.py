"""Verify that all required AI models are loadable.

Run from apps/backend/:
    uv run python scripts/verify_models.py
"""

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DIVIDER = "=" * 60


def verify_whisper() -> None:
    from faster_whisper import WhisperModel

    logger.info("Verifying Faster Whisper...")
    model = WhisperModel("medium", device="auto", compute_type="int8")
    logger.info("  OK  model=medium  type=faster-whisper")
    del model


def verify_pyannote() -> None:
    from pyannote.audio import Pipeline

    logger.info("Verifying Pyannote...")
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    logger.info("  OK  model=speaker-diarization-3.1")
    del pipeline


def verify_sentence_transformer() -> None:
    from sentence_transformers import SentenceTransformer

    logger.info("Verifying Sentence Transformer...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    dim = len(model.encode("MeetingMind"))
    logger.info("  OK  model=all-MiniLM-L6-v2  embedding_dim=%d", dim)
    del model


def verify_ollama() -> None:
    import ollama

    logger.info("Verifying Ollama...")
    models = ollama.list()
    names = [m.model for m in models.models]
    if names:
        for name in names:
            logger.info("  installed: %s", name)
    else:
        logger.warning("  Ollama is running but no models are installed.")


def main() -> None:
    checks = [
        ("Whisper", verify_whisper),
        ("Pyannote", verify_pyannote),
        ("Sentence Transformer", verify_sentence_transformer),
        ("Ollama", verify_ollama),
    ]

    results: list[tuple[str, bool]] = []
    for name, check in checks:
        logger.info(DIVIDER)
        try:
            check()
            results.append((name, True))
        except Exception as exc:
            logger.error("  FAILED: %s", exc)
            results.append((name, False))

    logger.info(DIVIDER)
    logger.info("Verification summary:")
    for name, ok in results:
        status = "OK" if ok else "FAILED"
        logger.info("  %-25s %s", name, status)


if __name__ == "__main__":
    main()
