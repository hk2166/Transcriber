"""The one place that turns settings into an LLM client.

Summaries, titles, and chat all call :func:`current_client` — switching the
provider/model/key in Settings changes every AI feature at once.
"""

from __future__ import annotations

from packages.intelligence import make_client
from settings import Settings, get_settings

__all__ = ["client_for", "current_client"]


def client_for(settings: Settings):
    """Build a client for an arbitrary Settings object (used by /llm/test)."""
    if settings.llm_provider == "ollama":
        return make_client("ollama", model=settings.ollama_model)
    return make_client(
        settings.llm_provider,
        model=settings.llm_model,
        api_key=settings.api_keys.get(settings.llm_provider, ""),
        base_url=settings.llm_base_url,
    )


def current_client():
    """Build the client for the currently configured provider."""
    return client_for(get_settings())
