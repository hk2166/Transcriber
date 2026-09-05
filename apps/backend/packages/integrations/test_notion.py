"""Notion target: link parsing, markdown encoding, parent resolution, apply, errors."""

from __future__ import annotations

import httpx
import pytest

from packages.integrations import INTEGRATIONS, INTEGRATIONS_BY_ID, NOTION, notion
from packages.integrations.base import IntegrationError, MeetingContext
from packages.integrations.notion import (
    Notion,
    NotionAPIError,
    NotionCredentials,
    ResolvedParent,
    build_create_page,
    escape_text,
    parse_parent_id,
    resolve_parent,
    to_notion_markdown,
    whoami,
)

ID = "1f2e3d4c5b6a7f8e9d0c1b2a3f4e5d6c"
DASHED = "1f2e3d4c-5b6a-7f8e-9d0c-1b2a3f4e5d6c"
CREDS = NotionCredentials(token="ntn_secret", parent=f"https://www.notion.so/Notes-{ID}")
NOT_FOUND = NotionAPIError("Confab can't see that page.", 404, "object_not_found")
PAGE = {
    "object": "page",
    "properties": {"title": {"type": "title", "title": [{"plain_text": "Meeting notes"}]}},
}
DATABASE = {
    "title": [{"plain_text": "Meetings"}],
    "data_sources": [{"id": "ds-1", "name": "Meetings"}],
}
DATA_SOURCE = {"properties": {"Name": {"type": "title", "title": {}}, "Date": {"type": "date"}}}

CTX = MeetingContext(
    meeting_id=1,
    title="Quarterly planning review",
    started_at="2026-08-23T14:00:00",
    summary="We agreed to freeze the build Wednesday.",
    action_items=["Freeze the build", "Draft release notes"],
    key_points=["Launch end of month"],
    decisions=["Freeze Wednesday"],
    open_questions=["Who owns the changelog?"],
)


class FakeAPI:
    """Scripted ``_request`` replacement keyed by (method, path); records calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, path, token, json=None):
        self.calls.append((method, path, token, json))
        result = self.routes[(method, path)]
        if isinstance(result, Exception):
            raise result
        return result


class FakeResponse:
    def __init__(self, status, data=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._data = {} if data is None else data

    def json(self):
        return self._data


def _script(monkeypatch, *responses):
    """Feed ``notion.httpx.request`` these responses in order; capture calls and sleeps."""
    calls: list[dict] = []
    queue = list(responses)

    def fake_request(method, url, headers=None, json=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers, "json": json})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(notion.httpx, "request", fake_request)
    monkeypatch.setattr(notion.time, "sleep", lambda seconds: calls.append({"slept": seconds}))
    return calls


# --- parse_parent_id --------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        f"https://www.notion.so/Quarterly-planning-{ID}",
        f"https://www.notion.so/acme/{ID}?v=0a1b2c3d4e5f60718293a4b5c6d7e8f9&pvs=4",
        f"https://www.notion.so/acme/Meetings-{ID}?v=0a1b2c3d4e5f60718293a4b5c6d7e8f9",
        DASHED,
        ID,
        f"  {ID.upper()}  ",
    ],
)
def test_parse_parent_id_accepts_links_and_ids(text):
    assert parse_parent_id(text) == ID


@pytest.mark.parametrize("text", ["", "https://www.notion.so/acme", "not a link", "a" * 40])
def test_parse_parent_id_rejects_garbage(text):
    with pytest.raises(IntegrationError, match="doesn't look like a Notion"):
        parse_parent_id(text)


# --- markdown encoding -------------------------------------------------------------

def test_escape_text_covers_every_syntax_character():
    raw = "\\*~`$[]<>{}|^"
    assert escape_text(raw) == "".join("\\" + char for char in raw)
    assert escape_text("plain words, punctuation. fine!") == "plain words, punctuation. fine!"


def test_to_notion_markdown_keeps_structure_and_escapes_text():
    body = (
        "# Title *x*\n## Key points\n- one [a]\n• two\n* three\n"
        "1. first\n2) second\n\nplain $5 <b>"
    )
    assert to_notion_markdown(body) == (
        "# Title \\*x\\*\n## Key points\n- one \\[a\\]\n- two\n- three\n"
        "1. first\n2. second\n\nplain \\$5 \\<b\\>"
    )
    assert to_notion_markdown("Just words.\n\nMore words.") == "Just words.\n\nMore words."


# --- propose / available / registry -------------------------------------------------

def test_propose_builds_sections_in_order():
    (draft,) = Notion().propose(CTX)
    assert (draft.kind, draft.target, draft.title, draft.payload) == (
        "page", "notion", CTX.title, {}
    )
    assert draft.body == (
        "We agreed to freeze the build Wednesday.\n\n"
        "## Key points\n- Launch end of month\n\n"
        "## Decisions\n- Freeze Wednesday\n\n"
        "## Action items\n- Freeze the build\n- Draft release notes\n\n"
        "## Open questions\n- Who owns the changelog?"
    )


def test_propose_skips_empty_sections_and_needs_a_summary():
    sparse = MeetingContext(1, "t", "2026-01-01T00:00", "Just a summary.", [], [], [], [])
    (draft,) = Notion().propose(sparse)
    assert draft.body == "Just a summary."
    assert Notion().propose(MeetingContext(1, "t", "2026-01-01T00:00", "", [], [], [], [])) == []


@pytest.mark.parametrize(
    "creds, expected",
    [
        (None, False),
        (NotionCredentials("", ID), False),
        (NotionCredentials("ntn_x", "  "), False),
        (NotionCredentials("ntn_x", ID), True),
    ],
)
def test_available_needs_token_and_parent(creds, expected):
    assert Notion(credentials=lambda: creds).available() is expected


def test_registry_ends_with_notion():
    assert INTEGRATIONS[-1] is NOTION and INTEGRATIONS_BY_ID["notion"] is NOTION
    assert NOTION.needs_token is True and Notion().available() is False
    assert all(target.needs_token is False for target in INTEGRATIONS[:-1])


# --- apply ---------------------------------------------------------------------------

def test_apply_creates_page_under_page_parent(monkeypatch):
    api = FakeAPI({
        ("GET", f"/pages/{ID}"): PAGE,
        ("POST", "/pages"): {"id": "p1", "url": "https://www.notion.so/Quarterly-p1"},
    })
    monkeypatch.setattr(notion, "_request", api)
    ref = Notion(credentials=lambda: CREDS).apply(
        "Quarterly *review*", "Summary.\n\n## Key points\n- a [b]", {}
    )
    assert ref.ref == ref.url == "https://www.notion.so/Quarterly-p1"
    method, path, token, body = api.calls[-1]
    assert (method, path, token) == ("POST", "/pages", "ntn_secret")
    assert body == {
        "parent": {"page_id": ID},
        "properties": {"title": {"title": [{"text": {"content": "Quarterly *review*"}}]}},
        "markdown": "Summary.\n\n## Key points\n- a \\[b\\]",
    }


def test_apply_creates_row_under_database_parent(monkeypatch):
    api = FakeAPI({
        ("GET", f"/pages/{ID}"): NOT_FOUND,
        ("GET", f"/databases/{ID}"): DATABASE,
        ("GET", "/data_sources/ds-1"): DATA_SOURCE,
        ("POST", "/pages"): {"id": "p2", "url": "https://www.notion.so/p2"},
    })
    monkeypatch.setattr(notion, "_request", api)
    ref = Notion(credentials=lambda: CREDS).apply("Standup", "Notes", {})
    assert ref.ref == "https://www.notion.so/p2"
    body = api.calls[-1][3]
    assert body["parent"] == {"data_source_id": "ds-1"}
    assert list(body["properties"]) == ["Name"]  # the data source's own title column


def test_apply_without_credentials_points_at_settings():
    with pytest.raises(IntegrationError, match="Settings"):
        Notion().apply("t", "b", {})


def test_build_create_page_clips_title():
    body = build_create_page(ResolvedParent("page", ID, "Notes", "title"), "x" * 2500, "md")
    assert len(body["properties"]["title"]["title"][0]["text"]["content"]) == 2000


# --- resolve_parent / whoami ---------------------------------------------------------

def test_resolve_parent_page_hit(monkeypatch):
    monkeypatch.setattr(notion, "_request", FakeAPI({("GET", f"/pages/{ID}"): PAGE}))
    assert resolve_parent("t", DASHED) == ResolvedParent("page", ID, "Meeting notes", "title")


def test_resolve_parent_falls_through_to_single_data_source(monkeypatch):
    api = FakeAPI({
        ("GET", f"/pages/{ID}"): NOT_FOUND,
        ("GET", f"/databases/{ID}"): DATABASE,
        ("GET", "/data_sources/ds-1"): DATA_SOURCE,
    })
    monkeypatch.setattr(notion, "_request", api)
    assert resolve_parent("t", ID) == ResolvedParent("data_source", "ds-1", "Meetings", "Name")


def test_resolve_parent_refuses_ambiguous_database(monkeypatch):
    api = FakeAPI({
        ("GET", f"/pages/{ID}"): NOT_FOUND,
        ("GET", f"/databases/{ID}"): {"data_sources": [{"id": "a"}, {"id": "b"}]},
    })
    monkeypatch.setattr(notion, "_request", api)
    with pytest.raises(IntegrationError, match="more than one data source"):
        resolve_parent("t", ID)


def test_resolve_parent_unshared_is_the_share_error(monkeypatch):
    api = FakeAPI({("GET", f"/pages/{ID}"): NOT_FOUND, ("GET", f"/databases/{ID}"): NOT_FOUND})
    monkeypatch.setattr(notion, "_request", api)
    with pytest.raises(NotionAPIError, match="can't see that page"):
        resolve_parent("t", ID)
    assert [call[1] for call in api.calls] == [f"/pages/{ID}", f"/databases/{ID}"]


def test_resolve_parent_reraises_non_404(monkeypatch):
    denied = NotionAPIError("Notion rejected the token.", 401, "unauthorized")
    monkeypatch.setattr(notion, "_request", FakeAPI({("GET", f"/pages/{ID}"): denied}))
    with pytest.raises(NotionAPIError, match="rejected the token"):
        resolve_parent("t", ID)


def test_whoami_names_bot_and_workspace(monkeypatch):
    me = {"name": "Confab", "bot": {"workspace_name": "Acme"}}
    monkeypatch.setattr(notion, "_request", FakeAPI({("GET", "/users/me"): me}))
    assert whoami("t") == {"bot_name": "Confab", "workspace_name": "Acme"}
    monkeypatch.setattr(notion, "_request", FakeAPI({("GET", "/users/me"): {"name": "Confab"}}))
    assert whoami("t")["workspace_name"] == ""


# --- _request: headers, error mapping, rate limiting ------------------------------

def test_request_sends_auth_and_version_headers(monkeypatch):
    calls = _script(monkeypatch, FakeResponse(200, {"ok": True}))
    assert notion._request("GET", "/users/me", "ntn_x") == {"ok": True}
    (call,) = calls
    assert call["url"] == "https://api.notion.com/v1/users/me"
    assert call["headers"] == {
        "Authorization": "Bearer ntn_x",
        "Notion-Version": "2026-03-11",
        "Content-Type": "application/json",
    }


@pytest.mark.parametrize(
    "status, code, message, expect",
    [
        (401, "unauthorized", "x", "rejected the token"),
        (403, "restricted_resource", "x", "enable Insert content"),
        (404, "object_not_found", "x", "add your Confab connection"),
        (400, "validation_error", "body.markdown should be a string", "should be a string"),
        (503, "service_unavailable", "x", "having trouble"),
        (529, "service_overload", "x", "having trouble"),
    ],
)
def test_request_maps_api_errors(monkeypatch, status, code, message, expect):
    _script(monkeypatch, FakeResponse(status, {"code": code, "message": message}))
    with pytest.raises(NotionAPIError, match=expect) as info:
        notion._request("GET", "/pages/x", "ntn_x")
    assert (info.value.status, info.value.code) == (status, code)


def test_request_retries_once_on_rate_limit(monkeypatch):
    calls = _script(
        monkeypatch,
        FakeResponse(429, {"code": "rate_limited"}, headers={"Retry-After": "2"}),
        FakeResponse(200, {"id": "ok"}),
    )
    assert notion._request("POST", "/pages", "ntn_x", json={}) == {"id": "ok"}
    assert [call for call in calls if "slept" in call] == [{"slept": 2.0}]
    assert sum("method" in call for call in calls) == 2


def test_request_gives_up_after_second_rate_limit(monkeypatch):
    calls = _script(
        monkeypatch,
        FakeResponse(429, {"code": "rate_limited"}, headers={"Retry-After": "60"}),
        FakeResponse(429, {"code": "rate_limited"}),
    )
    with pytest.raises(NotionAPIError, match="rate-limiting"):
        notion._request("POST", "/pages", "ntn_x", json={})
    assert [call["slept"] for call in calls if "slept" in call] == [5]  # capped at 5 s


def test_request_network_failure_is_friendly(monkeypatch):
    _script(monkeypatch, httpx.ConnectError("boom"))
    with pytest.raises(NotionAPIError, match="Couldn't reach Notion"):
        notion._request("GET", "/users/me", "ntn_x")
