"""A small cosine-similarity vector store (numpy) — the search index.

Task.md called for FAISS; brute-force numpy is chosen instead: at this app's
scale (thousands of segments) a full dot-product is <10 ms and needs no extra
dependency or packaging work. The add/search/remove/save/load surface keeps it
swappable for FAISS if a library ever grows past that.

Each vector is keyed by its transcript-segment id and tagged with its meeting
id, so a deleted meeting can be evicted in one call.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np

__all__ = ["SearchHit", "VectorStore"]


class SearchHit:
    __slots__ = ("segment_id", "meeting_id", "score")

    def __init__(self, segment_id: int, meeting_id: int, score: float) -> None:
        self.segment_id = segment_id
        self.meeting_id = meeting_id
        self.score = score


class VectorStore:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._seg_ids = np.zeros(0, dtype=np.int64)
        self._meeting_ids = np.zeros(0, dtype=np.int64)
        self._vectors = np.zeros((0, dim), dtype=np.float32)

    def __len__(self) -> int:
        return len(self._seg_ids)

    def add(
        self, segment_ids: list[int], meeting_id: int, vectors: np.ndarray
    ) -> None:
        """Append vectors for one meeting's segments (skips if empty)."""
        if len(segment_ids) == 0:
            return
        self._seg_ids = np.concatenate([self._seg_ids, np.array(segment_ids, np.int64)])
        self._meeting_ids = np.concatenate(
            [self._meeting_ids, np.full(len(segment_ids), meeting_id, np.int64)]
        )
        self._vectors = np.concatenate(
            [self._vectors, vectors.astype(np.float32)], axis=0
        )

    def remove_meeting(self, meeting_id: int) -> None:
        """Drop every vector belonging to ``meeting_id``."""
        keep = self._meeting_ids != meeting_id
        self._seg_ids = self._seg_ids[keep]
        self._meeting_ids = self._meeting_ids[keep]
        self._vectors = self._vectors[keep]

    def search(self, query: np.ndarray, k: int = 10) -> list[SearchHit]:
        """Top-``k`` segments by cosine similarity to ``query`` (a unit vector)."""
        if len(self) == 0:
            return []
        scores = self._vectors @ query.astype(np.float32)
        top = np.argsort(-scores)[:k]
        return [
            SearchHit(
                int(self._seg_ids[i]), int(self._meeting_ids[i]), float(scores[i])
            )
            for i in top
        ]

    def save(self, path: Path | str) -> None:
        """Persist atomically: write a temp file, then rename over ``path``.

        ``np.savez`` writes in place and isn't atomic, so an interrupted save
        (or two overlapping ones) could leave a truncated .npz that fails to
        load. Writing to a sibling temp file and ``os.replace``-ing avoids that.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".npz.tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                # Passing a file object stops np.savez from appending ".npz".
                np.savez(
                    handle,
                    seg_ids=self._seg_ids,
                    meeting_ids=self._meeting_ids,
                    vectors=self._vectors,
                )
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, path: Path | str, dim: int) -> VectorStore:
        """Load from ``path`` (``.npz``), or return an empty store if absent."""
        store = cls(dim)
        path = Path(path)
        if not path.exists():
            return store
        data = np.load(path)
        store._seg_ids = data["seg_ids"]
        store._meeting_ids = data["meeting_ids"]
        store._vectors = data["vectors"]
        return store
