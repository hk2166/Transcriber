"""Tests for the embedder (ONNX) and the numpy vector store."""

import numpy as np
import pytest

from packages.storage.vector_store import VectorStore


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.array(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def test_vector_store_ranks_by_similarity():
    store = VectorStore(dim=2)
    store.add([10, 11], meeting_id=1, vectors=np.array([_unit([1, 0]), _unit([0, 1])]))
    hits = store.search(_unit([0.9, 0.1]), k=2)
    assert [h.segment_id for h in hits] == [10, 11]
    assert hits[0].score > hits[1].score


def test_remove_meeting_evicts_its_vectors():
    store = VectorStore(dim=2)
    store.add([1, 2], meeting_id=1, vectors=np.array([_unit([1, 0]), _unit([1, 0.1])]))
    store.add([3], meeting_id=2, vectors=np.array([_unit([0, 1])]))
    store.remove_meeting(1)
    assert len(store) == 1
    hits = store.search(_unit([1, 0]), k=5)
    assert [h.segment_id for h in hits] == [3]


def test_save_and_load_roundtrip(tmp_path):
    store = VectorStore(dim=2)
    store.add([7], meeting_id=4, vectors=np.array([_unit([1, 1])]))
    path = tmp_path / "index.npz"
    store.save(path)

    loaded = VectorStore.load(path, dim=2)
    assert len(loaded) == 1
    hit = loaded.search(_unit([1, 1]), k=1)[0]
    assert hit.segment_id == 7 and hit.meeting_id == 4


def test_load_missing_returns_empty(tmp_path):
    store = VectorStore.load(tmp_path / "nope.npz", dim=384)
    assert len(store) == 0
    assert store.search(np.zeros(384, dtype=np.float32), k=5) == []


@pytest.fixture(scope="module")
def embedder():
    from packages.storage.embedder import Embedder

    return Embedder()


def test_embedder_shape_and_normalisation(embedder):
    vecs = embedder.encode(["hello world", "another sentence"])
    assert vecs.shape == (2, 384)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-4)


def test_embedder_semantic_ranking(embedder):
    query = embedder.encode_one("what did we decide about the budget?")
    budget = embedder.encode_one("we agreed the budget will increase next quarter")
    weather = embedder.encode_one("it might rain on the weekend")
    assert float(query @ budget) > float(query @ weather)


# ---- meeting-scoped search (the person-prep read path) ------------------------


def _two_meeting_store() -> VectorStore:
    store = VectorStore(dim=2)
    # Meeting 1 content points along x; meeting 2 along y.
    store.add([10, 11], meeting_id=1, vectors=np.array([_unit([1, 0]), _unit([0.9, 0.1])]))
    store.add([20, 21], meeting_id=2, vectors=np.array([_unit([0, 1]), _unit([0.1, 0.9])]))
    return store


def test_filter_excludes_other_meetings():
    store = _two_meeting_store()
    x_query = _unit([1, 0])  # unique to meeting 1's content
    assert store.search(x_query, k=5, meeting_ids={2}) != []  # still ranks within 2
    assert all(h.meeting_id == 2 for h in store.search(x_query, k=5, meeting_ids={2}))
    hits = store.search(x_query, k=5, meeting_ids={1})
    assert [h.segment_id for h in hits] == [10, 11]


def test_k_applies_within_the_filtered_scope():
    store = _two_meeting_store()
    # Global top-1 for a y-query is in meeting 2 — but scoped to meeting 1,
    # k=1 must still return meeting 1's best, not nothing.
    hits = store.search(_unit([0, 1]), k=1, meeting_ids={1})
    assert len(hits) == 1 and hits[0].meeting_id == 1


def test_none_filter_matches_unfiltered_exactly():
    store = _two_meeting_store()
    query = _unit([0.6, 0.4])
    plain = store.search(query, k=4)
    scoped = store.search(query, k=4, meeting_ids=None)
    assert [(h.segment_id, h.meeting_id, h.score) for h in plain] == [
        (h.segment_id, h.meeting_id, h.score) for h in scoped
    ]


def test_empty_filter_set_matches_nothing():
    store = _two_meeting_store()
    assert store.search(_unit([1, 0]), k=5, meeting_ids=set()) == []
    assert store.search(_unit([1, 0]), k=5, meeting_ids={99}) == []
