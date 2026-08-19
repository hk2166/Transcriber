"""Semantic search endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

import search_index
from search_index import SearchResult

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    k: int = 10


@router.post("")
def run_search(request: SearchRequest) -> list[SearchResult]:
    """Rank transcript segments across all meetings by semantic similarity."""
    return search_index.search(request.query, k=request.k)
