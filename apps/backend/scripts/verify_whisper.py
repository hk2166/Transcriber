"""Verify that Faster-Whisper can load the medium model.

Run from apps/backend/:
    uv run python scripts/verify_whisper.py
"""

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from faster_whisper import WhisperModel

    logger.info("Loading Whisper medium model...")
    model = WhisperModel("medium", device="auto", compute_type="int8")
    logger.info("Model loaded successfully.")
    del model


if __name__ == "__main__":
    main()
