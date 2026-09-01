"""The one place that turns settings into an LLM client.

Summaries, titles, and chat all call :func:`current_client` — switching the
provider/model/key in Settings changes every AI feature at once.
"""

from __future__ import annotations

from packages.intelligence import make_client
from settings import Settings, get_settings, resolve_api_key

__all__ = ["client_for", "current_client"]


def client_for(settings: Settings):
    """Build a client for an arbitrary Settings object (used by /llm/test)."""
    if settings.llm_provider == "ollama":
        return make_client("ollama", model=settings.ollama_model)
    return make_client(
        settings.llm_provider,
        model=settings.llm_model,
        # Keychain-resolved: the stored sentinel becomes the real key; a raw
        # just-typed value (e.g. /llm/test before saving) passes through.
        api_key=resolve_api_key(settings, settings.llm_provider),
        base_url=settings.llm_base_url,
    )


def current_client():
    """Build the client for the currently configured provider."""
    return client_for(get_settings())
