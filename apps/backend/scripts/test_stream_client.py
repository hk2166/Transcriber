"""Manual integration test: stream live session audio over the WebSocket.

Run from apps/backend/ with the server already running:
    uv run uvicorn main:app --host 127.0.0.1 --port 8765    # terminal 1
    uv run python -m scripts.test_stream_client             # terminal 2

Starts a 5-second "both" session, prints per-second stats decoded from the
base64 float32 stream, then stops the session and waits for the end-of-stream
message. Exits non-zero if no audio chunks arrive — this is Day 1's
"done when" check.
"""

import asyncio
import base64
import json
import logging
import urllib.request
from typing import Any

import numpy as np
import websockets

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:8765"
WS_URL = "ws://127.0.0.1:8765"
STREAM_SECONDS = 5


def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Blocking JSON POST — fine for a test script."""
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


async def main() -> None:
    start = post("/audio/start", {"source": "both"})
    session_id = start["session_id"]
    logger.info(
        "Session %s started (system_available=%s)",
        session_id,
        start["system_available"],
    )

    chunks = 0
    frames = 0
    window_squares = 0.0
    window_frames = 0

    async with websockets.connect(f"{WS_URL}/audio/stream/{session_id}") as ws:
        hello = json.loads(await ws.recv())
        logger.info("hello: %s", hello)
        sample_rate = hello["sample_rate"]

        loop = asyncio.get_running_loop()
        deadline = loop.time() + STREAM_SECONDS
        next_report = loop.time() + 1.0
        stopped = False

        while True:
            if not stopped and loop.time() >= deadline:
                stop = post("/audio/stop", {})
                logger.info(
                    "stop: %.2f s recorded → %s",
                    stop["duration_seconds"],
                    stop["wav_path"],
                )
                stopped = True

            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            except TimeoutError:
                logger.error("No message for 2 s — giving up.")
                break

            if message["type"] == "end":
                logger.info("End of stream received.")
                break
            if message["type"] != "audio":
                continue

            block = np.frombuffer(base64.b64decode(message["data"]), dtype=np.float32)
            chunks += 1
            frames += len(block)
            window_squares += float((block**2).sum())
            window_frames += len(block)

            if loop.time() >= next_report:
                rms = (window_squares / max(window_frames, 1)) ** 0.5
                logger.info(
                    "%3d chunks · %6d frames · window RMS %.4f", chunks, frames, rms
                )
                window_squares = 0.0
                window_frames = 0
                next_report += 1.0

    seconds = frames / sample_rate
    logger.info("Received %d chunks · %d frames · %.2f s of audio", chunks, frames, seconds)
    if chunks == 0:
        raise SystemExit("FAIL: no audio chunks received")
    logger.info("Day 1 done-when: PASSED")


if __name__ == "__main__":
    asyncio.run(main())
