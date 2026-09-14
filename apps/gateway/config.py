"""Gateway configuration from the environment (dev defaults for local runs).

Nothing here is a secret in the repo: real deployments set these via the host's
secret manager. The upstream key is the ONE legitimate provider key the hosted
free tier is metered against — never a pool of farmed accounts.
"""

from __future__ import annotations

import os

DB_PATH = os.environ.get("GATEWAY_DB", "gateway.db")

#: Guards the /admin API + dashboard. Set a real value in production.
ADMIN_TOKEN = os.environ.get("GATEWAY_ADMIN_TOKEN", "dev-admin-token")

#: The single funded upstream the hosted tier proxies to (OpenAI-compatible).
UPSTREAM_BASE_URL = os.environ.get("GATEWAY_UPSTREAM_URL", "https://api.openai.com/v1")
UPSTREAM_API_KEY = os.environ.get("GATEWAY_UPSTREAM_KEY", "")
UPSTREAM_MODEL = os.environ.get("GATEWAY_UPSTREAM_MODEL", "gpt-4o-mini")

#: Monthly free-tier token cap for a new user.
DEFAULT_TOKEN_LIMIT = int(os.environ.get("GATEWAY_FREE_LIMIT", "100000"))

_TIMEOUT = 60
