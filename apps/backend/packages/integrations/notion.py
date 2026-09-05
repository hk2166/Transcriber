"""Notion — file the meeting summary as a page in the user's workspace.

The first cloud target, on the same gate as the Apple apps: ``propose`` is
local-only, and ``apply`` runs for exactly one proposal the user approved
(docs/INTEGRATIONS.md). One pasted internal-connection token, one parent page
or database the user shares with that connection, one request per page. The
page they share is the only place Confab can write.

App-free by design: credentials arrive through the ``credentials`` callable
that ``proposal_service`` injects, and every HTTP call goes through the
module-level :func:`_request`, which tests monkeypatch the way they monkeypatch
``apple.run_osascript``.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from packages.integrations.base import (
    AppliedRef,
    IntegrationError,
    MeetingContext,
    ProposalDraft,
)

logger = logging.getLogger(__name__)

__all__ = [
    "API",
    "CONNECTIONS_URL",
    "NOTION_VERSION",
    "SETUP_HINT",
    "Notion",
    "NotionAPIError",
    "NotionCredentials",
    "ResolvedParent",
    "build_create_page",
    "escape_text",
    "parse_parent_id",
    "resolve_parent",
    "to_notion_markdown",
    "whoami",
]

API = "https://api.notion.com/v1"
#: Pinned: the ``markdown`` body on POST /pages is documented against this
#: version, and under it a database parent is addressed by data source.
NOTION_VERSION = "2026-03-11"
CONNECTIONS_URL = "https://app.notion.com/developers/connections"
SETUP_HINT = "Add your Notion token and a parent page in Settings."
_TIMEOUT = 20
_RETRY_CAP_S = 5

# User-facing texts (docs/INTEGRATIONS.md §7) — each is exactly what the card shows.
_MSG_BAD_LINK = "That doesn't look like a Notion page or database link."
_MSG_UNAUTHORIZED = (
    "Notion rejected the token. Paste a fresh installation token in Settings → Notion."
)
_MSG_FORBIDDEN = (
    "This connection can't create pages here. In Notion's developer portal, enable "
    "Insert content for it, then retry."
)
_MSG_NOT_FOUND = (
    "Confab can't see that page. In Notion, open it → ••• → Connections → add your "
    "Confab connection, then retry."
)
_MSG_RATE_LIMITED = "Notion is rate-limiting requests. Try again in a moment."
_MSG_OFFLINE = "Couldn't reach Notion. Check your connection and retry."
_MSG_DOWN = "Notion is having trouble right now. Retry in a minute."
_MSG_MANY_SOURCES = (
    "This database has more than one data source. Paste the data source link instead "
    "(Manage data sources → Copy data source ID)."
)


class NotionAPIError(IntegrationError):
    """An API failure, already worded for the card. ``status`` lets callers
    branch — :func:`resolve_parent` falls through to a database on 404."""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class NotionCredentials:
    token: str
    parent: str  # the pasted page/database link or id, exactly as typed


@dataclass
class ResolvedParent:
    kind: Literal["page", "data_source"]
    id: str
    title: str
    title_property: str  # "title" for pages; the database's title column otherwise


# --- pure helpers ---------------------------------------------------------------

#: A 32-hex id or a dashed UUID that is not part of a longer hex run (a 40-hex
#: git SHA must not yield its first 32 characters).
_ID = re.compile(
    r"(?<![0-9a-fA-F])"
    r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(?![0-9a-fA-F])"
)
_SYNTAX = re.compile(r"([\\*~`$\[\]<>{}|^])")
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET = re.compile(r"^[-•*]\s+(.*)$")
_NUMBERED = re.compile(r"^(\d+)[.)]\s+(.*)$")


def parse_parent_id(text: str) -> str:
    """The 32-hex id in a pasted Notion link or id.

    Accepts ``notion.so/Title-<id>``, ``notion.so/<workspace>/<id>?v=...``, a
    dashed UUID, or a bare id. The query string goes first: a database link
    carries a second 32-hex id (the view) in ``?v=``.
    """
    path = (text or "").strip().split("?", 1)[0].split("#", 1)[0]
    matches = _ID.findall(path)
    if not matches:
        raise IntegrationError(_MSG_BAD_LINK)
    return matches[-1].replace("-", "").lower()


def escape_text(text: str) -> str:
    """Backslash-escape Notion-flavored-Markdown syntax so text renders literally."""
    return _SYNTAX.sub(r"\\\1", text)


def to_notion_markdown(body: str) -> str:
    """Encode the editable body as Notion-flavored Markdown, line by line.

    Structure the user typed — headings, bullets, numbering — is kept; only
    the text inside each line is escaped. What the card shows is what the page
    shows: an LLM's stray ``*`` or ``[`` never becomes italics or a link.
    """
    out: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            out.append("")
        elif match := _HEADING.match(line):
            out.append(f"{match.group(1)} {escape_text(match.group(2).strip())}")
        elif match := _BULLET.match(line):
            out.append(f"- {escape_text(match.group(1).strip())}")
        elif match := _NUMBERED.match(line):
            out.append(f"{match.group(1)}. {escape_text(match.group(2).strip())}")
        else:
            out.append(escape_text(line))
    return "\n".join(out)


def build_create_page(parent: ResolvedParent, title: str, markdown: str) -> dict[str, Any]:
    """The POST /pages body: parent, one title property, the page as markdown."""
    parent_key = "page_id" if parent.kind == "page" else "data_source_id"
    return {
        "parent": {parent_key: parent.id},
        "properties": {
            parent.title_property: {"title": [{"text": {"content": title[:2000]}}]}
        },
        "markdown": markdown,
    }


# --- HTTP -------------------------------------------------------------------------

def _request(method: str, path: str, token: str, json: dict | None = None) -> dict[str, Any]:
    """One Notion API call → parsed JSON. Raises :class:`NotionAPIError`.

    Retries a 429 once after ``Retry-After`` (capped at ``_RETRY_CAP_S``);
    every other failure maps straight to a user-facing message.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    url = f"{API}{path}"
    for attempt in range(2):
        try:
            response = httpx.request(method, url, headers=headers, json=json, timeout=_TIMEOUT)
        except httpx.HTTPError as exc:
            raise NotionAPIError(_MSG_OFFLINE) from exc
        if response.status_code == 429 and attempt == 0:
            wait = _retry_after(response)
            logger.info("Notion rate-limited %s %s — retrying in %.0fs.", method, path, wait)
            time.sleep(wait)
            continue
        break
    if 200 <= response.status_code < 300:
        return response.json()
    raise _api_error(response)


def _retry_after(response: Any) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", 1))
    except (TypeError, ValueError):
        seconds = 1.0
    return max(0.0, min(seconds, _RETRY_CAP_S))


def _api_error(response: Any) -> NotionAPIError:
    status = response.status_code
    code, message = "", ""
    try:
        body = response.json()
        code = str(body.get("code") or "")
        message = str(body.get("message") or "")
    except Exception:
        pass
    if status == 401:
        text = _MSG_UNAUTHORIZED
    elif status == 403:
        text = _MSG_FORBIDDEN
    elif status == 404:
        text = _MSG_NOT_FOUND
    elif status == 429:
        text = _MSG_RATE_LIMITED
    elif status == 400:
        text = message[:300] or "Notion rejected the request."
    elif status >= 500:
        text = _MSG_DOWN
    else:
        text = message[:300] or f"Notion returned HTTP {status}."
    return NotionAPIError(text, status, code)


def whoami(token: str) -> dict[str, str]:
    """Prove the token works; name the bot and workspace for the Settings result line."""
    me = _request("GET", "/users/me", token)
    bot = me.get("bot") or {}
    return {
        "bot_name": str(me.get("name") or ""),
        "workspace_name": str(bot.get("workspace_name") or ""),
    }


def resolve_parent(token: str, parent: str) -> ResolvedParent:
    """Where the page will land — resolved on every use, never cached.

    A page the connection can see wins. Otherwise the id is tried as a
    database: its single data source becomes the parent, and that data
    source's ``title``-typed property names the column the page title goes
    in. A 404 on both means the user hasn't shared it with the connection.
    """
    parent_id = parse_parent_id(parent)
    try:
        page = _request("GET", f"/pages/{parent_id}", token)
    except NotionAPIError as exc:
        if exc.status != 404:
            raise
    else:
        return ResolvedParent("page", parent_id, _page_title(page), "title")

    database = _request("GET", f"/databases/{parent_id}", token)  # 404 → the share error
    sources = database.get("data_sources") or []
    if len(sources) != 1:
        raise IntegrationError(_MSG_MANY_SOURCES)
    source_id = str(sources[0].get("id") or "")
    source = _request("GET", f"/data_sources/{source_id}", token)
    title_property = next(
        (
            name
            for name, prop in (source.get("properties") or {}).items()
            if isinstance(prop, dict) and prop.get("type") == "title"
        ),
        "title",
    )
    return ResolvedParent(
        "data_source", source_id, _rich_text(database.get("title")) or "Untitled", title_property
    )


def _page_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _rich_text(prop.get("title")) or "Untitled"
    return "Untitled"


def _rich_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    return "".join(str(p.get("plain_text") or "") for p in parts if isinstance(p, dict)).strip()


# --- the integration ----------------------------------------------------------------

@dataclass
class Notion:
    id: str = "notion"
    label: str = "Notion"
    needs_token: bool = True
    #: Injected by proposal_service — the single app-level wire. Default: unconfigured.
    credentials: Callable[[], NotionCredentials | None] = field(default=lambda: None)

    def _configured(self) -> NotionCredentials | None:
        creds = self.credentials()
        if creds is None or not creds.token.strip() or not creds.parent.strip():
            return None
        return creds

    def available(self) -> bool:
        """Token and parent present. No network: this runs on every propose."""
        return self._configured() is not None

    def propose(self, ctx: MeetingContext) -> list[ProposalDraft]:
        if not ctx.summary:
            return []
        lines = [ctx.summary.strip()]
        for heading, items in (
            ("Key points", ctx.key_points),
            ("Decisions", ctx.decisions),
            ("Action items", ctx.action_items),
            ("Open questions", ctx.open_questions),
        ):
            if items:
                lines += ["", f"## {heading}", *(f"- {item}" for item in items)]
        return [
            ProposalDraft(kind="page", target=self.id, title=ctx.title, body="\n".join(lines))
        ]

    def apply(self, title: str, body: str, payload: dict) -> AppliedRef:
        """One request is the commit point: the whole page goes in the create call."""
        creds = self._configured()
        if creds is None:
            raise IntegrationError(SETUP_HINT)
        parent = resolve_parent(creds.token, creds.parent)
        page = _request(
            "POST",
            "/pages",
            creds.token,
            json=build_create_page(parent, title, to_notion_markdown(body)),
        )
        url = str(page.get("url") or page.get("id") or "")
        return AppliedRef(ref=url, url=url)
