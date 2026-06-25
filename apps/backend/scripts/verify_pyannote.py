"""Verify that the Pyannote speaker diarization pipeline can be loaded.

Run from apps/backend/:
    uv run python scripts/verify_pyannote.py
"""

import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from pyannote.audio import Pipeline

    logger.info("Loading speaker diarization model...")
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    logger.info("Pyannote model loaded successfully.")
    del pipeline


if __name__ == "__main__":
    main()
