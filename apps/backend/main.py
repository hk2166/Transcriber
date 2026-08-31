"""Confab backend entry point.

Start with:
    uv run uvicorn main:app --host 127.0.0.1 --port 8765 --reload
"""

import logging
import logging.config
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import meeting_detect
from database import close_db, get_db
from routers.action_items import router as action_items_router
from routers.audio import router as audio_router
from routers.google import router as google_router
from routers.proposals import router as proposals_router
from routers.chat import router as chat_router
from routers.export import router as export_router
from routers.meetings import router as meetings_router
from routers.search import router as search_router
from routers.settings import router as settings_router
from routers.speakers import router as speakers_router
from routers.transcription import router as transcription_router

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                "datefmt": "%H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "root": {"level": "INFO", "handlers": ["console"]},
    }
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio
    from contextlib import suppress

    import postprocess_job
    from sessions import manager

    get_db()  # open + migrate before serving
    # Recover any meeting a previous crash / force-quit left stuck before serving.
    postprocess_job.reconcile_interrupted_meetings()
    detect_task = asyncio.create_task(meeting_detect.poller())
    yield
    detect_task.cancel()
    with suppress(asyncio.CancelledError):
        await detect_task
    # Quitting mid-recording (Cmd-Q) lands here: flush the WAV and mark the
    # meeting so the next launch's reconciliation finishes it — never lose it.
    try:
        manager.finalize_for_shutdown()
    except Exception:
        logger.exception("Error finalizing the active session on shutdown.")
    close_db()


app = FastAPI(
    title="Confab",
    description="Local AI meeting assistant — 100% offline.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        # Packaged Tauri webview origins (Day 7 sidecar).
        "tauri://localhost",
        "http://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    """Never leak a stack trace to the client — log it, return a friendly 500."""
    from fastapi.responses import JSONResponse

    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on the backend. Please try again."},
    )


app.include_router(audio_router)
app.include_router(transcription_router)
app.include_router(meetings_router)
app.include_router(speakers_router)
app.include_router(search_router)
app.include_router(chat_router)
app.include_router(export_router)
app.include_router(settings_router)
app.include_router(action_items_router)
app.include_router(proposals_router)
app.include_router(google_router)

@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
