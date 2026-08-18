"""Assign speakers to transcript segments by maximum temporal overlap.

Pure functions — no model, no torch — so they're fast to test.
"""

from __future__ import annotations

from collections.abc import Sequence

from packages.diarization.diarizer import SpeakerTurn

__all__ = ["assign_speaker", "assign_speakers"]


def assign_speaker(
    start_ms: int, end_ms: int, turns: Sequence[SpeakerTurn]
) -> str | None:
    """Return the speaker whose turns overlap ``[start_ms, end_ms]`` most.

    ``None`` if nothing overlaps (e.g. the segment fell entirely in a gap
    between diarized turns).
    """
    best_speaker: str | None = None
    best_overlap = 0
    for turn in turns:
        overlap = min(end_ms, turn.end_ms) - max(start_ms, turn.start_ms)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker
    return best_speaker


def assign_speakers(
    segments: Sequence[tuple[int, int]], turns: Sequence[SpeakerTurn]
) -> list[str | None]:
    """Map each ``(start_ms, end_ms)`` segment to its best-overlap speaker."""
    return [assign_speaker(start, end, turns) for start, end in segments]
