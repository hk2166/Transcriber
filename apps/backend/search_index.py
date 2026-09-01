"""Semantic search index — embeds transcript segments, answers queries.

The embedder and the on-disk vector store load lazily on first use, so the
live capture/transcribe path never touches them. The store persists to
``search_index.npz`` in the app data dir; deleting a meeting evicts its
vectors without needing the (heavier) embedder.
"""

from __future__ import annotations

import gc
import logging
import threading
from dataclasses import dataclass

from database import get_db
from packages.audio import default_recordings_dir
from packages.storage import get_meeting, get_segments, get_segments_by_ids
from packages.storage.embedder import Embedder
from packages.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)

_embedder: Embedder | None = None
_store: VectorStore | None = None
_lock = threading.Lock()  # guards lazy init of the singletons
#: Serialises store mutation+save. Index edits, post-meeting indexing, and
#: deletes all mutate the one store from different threads; without this their
#: read-modify-write on the parallel arrays (and the .npz save) can interleave
#: and corrupt the index. Distinct from _lock to keep a simple lock order
#: (_write_lock → _lock, never the reverse).
_write_lock = threading.Lock()


@dataclass
class SearchResult:
    meeting_id: int
    meeting_title: str
    segment_id: int
    text: str
    start_ms: int
    score: float


def _index_path():
    return default_recordings_dir().parent / "search_index.npz"


def _get_embedder() -> Embedder:
    global _embedder
    with _lock:
        if _embedder is None:
            _embedder = Embedder()
    return _embedder


def get_embedder() -> Embedder:
    """Public accessor for the shared embedder (reused by RAG chat)."""
    return _get_embedder()


def release_embedder() -> None:
    """Drop the cached embedder to free memory (reloads on next use).

    Used by post-processing so the ONNX embedder isn't held resident after
    indexing on low-memory machines."""
    global _embedder
    with _lock:
        _embedder = None
    gc.collect()


def reset() -> None:
    """Forget the loaded index (after a data reset)."""
    global _store
    with _lock:
        _store = None


def _get_store() -> VectorStore:
    global _store
    with _lock:
        if _store is None:
            _store = VectorStore.load(_index_path(), Embedder.DIM)
    return _store


def index_meeting(meeting_id: int) -> None:
    """Embed a meeting's segments into the index (idempotent re-index)."""
    segments = get_segments(get_db(), meeting_id)
    if not segments:
        return
    embedder = _get_embedder()
    # Encoding is slow and touches nothing shared — keep it out of the lock.
    vectors = embedder.encode([s.text for s in segments])
    with _write_lock:
        store = _get_store()
        store.remove_meeting(meeting_id)
        store.add([s.id for s in segments], meeting_id, vectors)
        store.save(_index_path())
    logger.info("Indexed %d segments for meeting %d.", len(segments), meeting_id)


def remove_meeting(meeting_id: int) -> None:
    """Evict a deleted meeting's vectors (store only — no embedder needed)."""
    if _store is None and not _index_path().exists():
        return
    with _write_lock:
        store = _get_store()
        store.remove_meeting(meeting_id)
        store.save(_index_path())


def search(query: str, k: int = 10) -> list[SearchResult]:
    """Top-``k`` transcript segments most similar to ``query``."""
    text = query.strip()
    if not text:
        return []
    embedder = _get_embedder()
    store = _get_store()
    hits = store.search(embedder.encode_one(text), k=k)
    if not hits:
        return []

    db = get_db()
    segments = get_segments_by_ids(db, [h.segment_id for h in hits])
    titles: dict[int, str] = {}
    results: list[SearchResult] = []
    for hit in hits:
        segment = segments.get(hit.segment_id)
        if segment is None:  # index/DB drift — skip
            continue
        if hit.meeting_id not in titles:
            meeting = get_meeting(db, hit.meeting_id)
            titles[hit.meeting_id] = meeting.title if meeting else "Meeting"
        results.append(
            SearchResult(
                meeting_id=hit.meeting_id,
                meeting_title=titles[hit.meeting_id],
                segment_id=hit.segment_id,
                text=segment.text,
                start_ms=segment.start_ms,
                score=round(hit.score, 3),
            )
        )
    return results
