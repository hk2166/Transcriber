"""Confab Gateway — the opt-in hosted tier's control plane.

Local-first stays the default in the app; this service exists only for users
who opt into the metered "Confab Hosted" provider. It holds ONE funded upstream
key, meters per-user monthly token caps, and gives an admin dashboard to manage
access. It never stores meeting content — only token counts.

Run:  cd apps/gateway && uvicorn main:app --port 8900 --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from db import close_db, get_db
from routers.admin import router as admin_router
from routers.auth import router as auth_router
from routers.proxy import router as proxy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()
    yield
    close_db()


app = FastAPI(title="Confab Gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # desktop clients dial in from many origins; token is the guard
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(proxy_router)
app.include_router(admin_router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/admin", include_in_schema=False)
def admin_dashboard() -> FileResponse:
    """The admin dashboard (enter the admin token once, in the page)."""
    return FileResponse(Path(__file__).parent / "admin.html")
