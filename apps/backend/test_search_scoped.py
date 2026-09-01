"""Meeting-scoped semantic search over PERSISTED vectors (person-prep path)."""

from __future__ import annotations

from datetime import datetime

import pytest

import search_index
from packages.storage import connect, create_meeting, insert_segment


@pytest.fixture
def scoped_index(tmp_path, monkeypatch):
    """A real (temp) index + in-memory DB with two distinct meetings."""
    conn = connect(":memory:")
    monkeypatch.setattr(search_index, "get_db", lambda: conn)
    monkeypatch.setattr(search_index, "_index_path", lambda: tmp_path / "idx.npz")
    search_index.reset()

    a = create_meeting(conn, source="mic", wav_path=None,
                       started_at=datetime(2026, 9, 1, 9, 0))
    b = create_meeting(conn, source="mic", wav_path=None,
                       started_at=datetime(2026, 9, 2, 9, 0))
    for text in ["the quarterly budget will increase", "hiring two backend engineers"]:
        insert_segment(conn, a, text=text, start_ms=0, end_ms=1000,
                       language="en", confidence=0.9)
    for text in ["the kubernetes deployment keeps crashing", "we rotated the tls certificates"]:
        insert_segment(conn, b, text=text, start_ms=0, end_ms=1000,
                       language="en", confidence=0.9)
    search_index.index_meeting(a)
    search_index.index_meeting(b)
    yield a, b
    search_index.reset()
    conn.close()


def test_scope_excludes_other_meetings(scoped_index):
    a, b = scoped_index
    # Budget talk lives only in meeting A.
    wrong_scope = search_index.search_meetings("budget increase", meeting_ids={b})
    assert all(r.meeting_id == b for r in wrong_scope)
    assert not any("budget" in r.text for r in wrong_scope)

    right_scope = search_index.search_meetings("budget increase", meeting_ids={a})
    assert right_scope and right_scope[0].meeting_id == a
    assert "budget" in right_scope[0].text


def test_scoped_results_match_global_shape(scoped_index):
    a, _ = scoped_index
    scoped = search_index.search_meetings("budget", meeting_ids={a}, k=1)[0]
    glob = search_index.search("budget", k=1)[0]
    assert type(scoped) is type(glob)
    assert scoped.segment_id == glob.segment_id  # same best hit, read from disk
    assert scoped.meeting_title == glob.meeting_title


def test_scoped_reads_persisted_vectors_not_reembeds(scoped_index, monkeypatch):
    a, _ = scoped_index

    class _NoBatchEncode:
        DIM = 384

        def __init__(self, real):
            self._real = real

        def encode_one(self, text):  # query embedding is allowed
            return self._real.encode_one(text)

        def encode(self, texts):  # corpus re-embedding is NOT
            raise AssertionError("search_meetings must not re-embed the corpus")

    real = search_index.get_embedder()
    monkeypatch.setattr(search_index, "_get_embedder",
                        lambda: _NoBatchEncode(real))
    hits = search_index.search_meetings("budget", meeting_ids={a})
    assert hits  # served entirely from the persisted store


def test_empty_scope_and_blank_query_return_nothing(scoped_index):
    a, _ = scoped_index
    assert search_index.search_meetings("budget", meeting_ids=set()) == []
    assert search_index.search_meetings("   ", meeting_ids={a}) == []


def test_context_windows_overlap_with_one_entry_per_segment():
    fn = search_index._context_windows
    assert fn(["a"]) == ["a"]
    assert fn(["a", "b"]) == ["a b", "a b"]
    assert fn(["a", "b", "c", "d"]) == ["a b", "a b c", "b c d", "c d"]
    assert len(fn(list("abcdefg"))) == 7  # cardinality preserved
