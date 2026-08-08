"""Manual integration test: record 5 seconds of mixed mic + system audio.

Run from apps/backend/:
    uv run python -m scripts.test_mixed_capture

For the system half to carry sound, output must be routed through BlackHole
(Multi-Output Device in Audio MIDI Setup), same as test_capture.py.
Speak AND play music during the recording.
"""

import logging
import time

import numpy as np
import soundfile as sf

from packages.audio import MixedAudioCapture

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

chunks: list[np.ndarray] = []


def main() -> None:
    capture = MixedAudioCapture(callback=chunks.append)
    logger.info("System audio available: %s", capture.system_available)

    with capture:
        logger.info("Recording mixed audio for 5 seconds — speak and play music...")
        time.sleep(5)

    if not chunks:
        raise RuntimeError("No audio blocks were captured!")

    audio = np.concatenate(chunks, axis=0)
    sf.write("test_mixed_output.wav", audio, MixedAudioCapture.SAMPLE_RATE)
    logger.info("Saved recording to test_mixed_output.wav (%d samples)", len(audio))


if __name__ == "__main__":
    main()
