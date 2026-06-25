"""Manual integration test: record 5 seconds of system audio via BlackHole.

Run from apps/backend/:
    uv run python scripts/test_capture.py
"""

import logging
import time

import numpy as np
import soundfile as sf

from packages.audio.capture import SystemAudioCapture

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

chunks: list[np.ndarray] = []


def on_audio(data: np.ndarray) -> None:
    chunks.append(data)


def main() -> None:
    device = SystemAudioCapture.find_device()

    with SystemAudioCapture(device=device, callback=on_audio):
        logger.info("Recording system audio for 5 seconds...")
        time.sleep(5)

    if not chunks:
        raise RuntimeError("No audio was captured.")

    audio = np.concatenate(chunks, axis=0)
    sf.write("test_output.wav", audio, SystemAudioCapture.SAMPLE_RATE)
    logger.info("Saved recording to test_output.wav (%d samples)", len(audio))


if __name__ == "__main__":
    main()
