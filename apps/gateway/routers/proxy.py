"""The metered LLM proxy: the ONE path hosted-tier requests take.

Authenticates the user, enforces status + the monthly free-tier cap, forwards
to the single funded upstream, meters the returned token usage. No meeting
content is stored — only token counts.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import providers
import store
from auth import UserDep
from db import get_db

router = APIRouter(tags=["proxy"])


@router.post("/v1/chat/completions")
def chat_completions(payload: dict, user=UserDep) -> dict:
    db = get_db()
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="This account is disabled.")
    if store.remaining(db, user) <= 0:
        raise HTTPException(
            status_code=402,
            detail="Free tier used up for this month. Add your own key or use local (Ollama).",
        )
    try:
        result = providers.chat_completion(payload)
    except providers.UpstreamError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    usage = result.get("usage") or {}
    store.record_usage(
        db,
        user["id"],
        model=result.get("model") or payload.get("model") or "",
        prompt=int(usage.get("prompt_tokens") or 0),
        completion=int(usage.get("completion_tokens") or 0),
    )
    return result
