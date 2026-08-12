"""Manual test: print live transcript JSON from a recording session.

Run from apps/backend/ with the server running:
    uv run python -m scripts.test_transcript

Starts a 'both' session, prints each TranscriptSegment as JSON while you
speak (or play audio), then stops after RECORD_SECONDS. The session is always
stopped on exit, even if the stream errors, so no session is left orphaned.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request

import websockets

BASE_URL = "http://127.0.0.1:8765"
WS_URL = "ws://127.0.0.1:8765"
RECORD_SECONDS = 20

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def post(path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        method="POST",
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


async def main() -> None:
    start = post("/audio/start", {"source": "both"})
    session_id = start["session_id"]
    logger.info("Session %s — speak now (auto-stops in %ds)", session_id, RECORD_SECONDS)

    async def stop_after_delay() -> None:
        await asyncio.sleep(RECORD_SECONDS)
        logger.info("[stopping]")
        await asyncio.to_thread(post, "/audio/stop")

    stopper = asyncio.create_task(stop_after_delay())
    try:
        async with websockets.connect(f"{WS_URL}/transcription/stream/{session_id}") as ws:
            while True:
                # Generous timeout: the first transcript waits on the one-time
                # model load, then a segment plus its ~1 s of transcription.
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=RECORD_SECONDS + 30)
                except TimeoutError:
                    logger.info("[timed out waiting for the backend]")
                    break
                msg = json.loads(raw)
                if msg["type"] == "end":
                    logger.info("[end of stream]")
                    break
                if msg["type"] == "transcript":
                    logger.info(json.dumps(msg, ensure_ascii=False))
    finally:
        stopper.cancel()
        # Guarantee the session is stopped; ignore 409 if it already is.
        try:
            await asyncio.to_thread(post, "/audio/stop")
        except urllib.error.HTTPError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
