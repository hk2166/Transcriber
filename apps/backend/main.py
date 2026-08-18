"""MeetingMind backend entry point.

Start with:
    uv run uvicorn main:app --host 127.0.0.1 --port 8765 --reload
"""

import logging
import logging.config
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import close_db, get_db
from routers.audio import router as audio_router
from routers.meetings import router as meetings_router
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
    get_db()  # open + migrate before serving
    yield
    close_db()


app = FastAPI(
    title="MeetingMind",
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

app.include_router(audio_router)
app.include_router(transcription_router)
app.include_router(meetings_router)

@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
