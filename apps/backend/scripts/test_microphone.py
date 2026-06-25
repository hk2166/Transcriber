"""Manual integration test: record 5 seconds of microphone audio.

Run from apps/backend/:
    uv run python scripts/test_microphone.py
"""

import logging
import time

import numpy as np
import soundfile as sf

from packages.audio.capture import MicrophoneCapture

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

chunks: list[np.ndarray] = []


def on_audio(data: np.ndarray) -> None:
    chunks.append(data)


def main() -> None:
    device = MicrophoneCapture.find_device()

    logger.info("Recording microphone for 5 seconds — speak now!")
    with MicrophoneCapture(device=device, callback=on_audio):
        time.sleep(5)

    if not chunks:
        raise RuntimeError("No microphone audio was captured.")

    audio = np.concatenate(chunks, axis=0)
    sf.write("test_mic.wav", audio, MicrophoneCapture.SAMPLE_RATE)
    logger.info(
        "Saved recording to test_mic.wav (%d samples)", len(audio)
    )


if __name__ == "__main__":
    main()
