"""Google connect flow: setup guidance, credentials, OAuth loopback, status."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import google_service
from google_service import GoogleAuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["google"])


@router.get("/setup")
def setup() -> dict[str, Any]:
    """The one-time project setup: gcloud script + console deep-links."""
    plan = google_service.setup_plan()
    return {
        "gcloud_available": plan.gcloud_available,
        "script": plan.script,
        "links": plan.links,
    }


@router.get("/status")
def status() -> dict[str, Any]:
    return google_service.status()


class Credentials(BaseModel):
    client_id: str
    client_secret: str


@router.post("/credentials")
def credentials(body: Credentials) -> dict[str, bool]:
    google_service.save_client(body.client_id, body.client_secret)
    return {"saved": True}


class ConnectRequest(BaseModel):
    redirect_base: str  # the frontend's own 127.0.0.1 origin


@router.post("/connect")
def connect(body: ConnectRequest) -> dict[str, str]:
    """Return the consent URL for the frontend to open in the system browser."""
    try:
        return {"auth_url": google_service.begin_connect(body.redirect_base)}
    except GoogleAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/callback", response_class=HTMLResponse)
def callback(
    state: str = "", code: str = "", error: str = ""
) -> HTMLResponse:
    """The loopback target Google redirects the browser to."""
    if error:
        return _page("Sign-in was cancelled.", ok=False)
    try:
        email = google_service.complete_callback(state, code)
    except GoogleAuthError as exc:
        return _page(str(exc), ok=False)
    who = f" as {email}" if email else ""
    return _page(f"Confab is now connected to Google{who}.", ok=True)


@router.post("/disconnect")
def disconnect() -> dict[str, bool]:
    google_service.disconnect()
    return {"disconnected": True}


def _page(message: str, *, ok: bool) -> HTMLResponse:
    color = "#111" if ok else "#b3261e"
    return HTMLResponse(
        f"""<!doctype html><meta charset=utf-8>
<title>Confab · Google</title>
<style>
  body {{ font: 16px -apple-system, system-ui, sans-serif; background:#fafafa;
    color:{color}; display:grid; place-items:center; height:100vh; margin:0; }}
  .card {{ background:#fff; border:1px solid #0001; border-radius:14px;
    padding:32px 40px; max-width:380px; text-align:center; box-shadow:0 8px 30px #0001; }}
  h1 {{ font-size:17px; margin:0 0 8px; }}
  p {{ color:#666; font-size:14px; margin:0; }}
</style>
<div class=card><h1>{"✓ Connected" if ok else "Couldn't connect"}</h1>
<p>{message}<br>You can close this tab and return to Confab.</p></div>""",
        status_code=200 if ok else 400,
    )
