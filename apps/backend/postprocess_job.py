"""Post-meeting processing: diarize speakers, then summarize with the local LLM.

Runs in the background after a session ends. Each stage degrades gracefully —
diarization needs torch, summaries need Ollama, and the app must still work
(and reach ``ready``) when either is missing.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from database import get_db
from packages.diarization import SpeakerDiarizer, assign_speaker
from packages.intelligence import (
    OllamaClient,
    OllamaUnavailable,
    generate_title,
    summarize,
)
from packages.storage import (
    Segment,
    create_speakers,
    get_segments,
    get_speakers,
    replace_action_items,
    save_summary,
    set_meeting_status,
    set_meeting_title,
    set_segment_speaker,
)
from settings import get_settings

logger = logging.getLogger(__name__)

_diarizer: SpeakerDiarizer | None = None
_diarizer_lock = threading.Lock()
_tasks: set[asyncio.Task] = set()


def _get_diarizer() -> SpeakerDiarizer:
    global _diarizer
    with _diarizer_lock:
        if _diarizer is None:
            _diarizer = SpeakerDiarizer()
    return _diarizer


async def _diarization_turns(wav_path: str) -> list:
    """In-process pyannote if importable (dev), else the optional speaker
    pack's subprocess (packaged app). Raises when neither is available."""
    try:
        diarizer = await asyncio.to_thread(_get_diarizer)
        return await asyncio.to_thread(diarizer.diarize_file, wav_path)
    except Exception:
        import speaker_pack

        if speaker_pack.installed():
            logger.info("In-process diarization unavailable — using the speaker pack.")
            return await asyncio.to_thread(speaker_pack.diarize_file, wav_path)
        raise


async def _diarize(meeting_id: int, wav_path: str, segments: list[Segment]) -> None:
    turns = await _diarization_turns(wav_path)
    labels = [turn.speaker for turn in turns]
    if not labels:
        return
    db = get_db()
    mapping = create_speakers(db, meeting_id, labels)
    for segment in segments:
        label = assign_speaker(segment.start_ms, segment.end_ms, turns)
        if label is not None:
            set_segment_speaker(db, segment.id, mapping[label])


def _build_transcript(meeting_id: int, segments: list[Segment]) -> str:
    db = get_db()
    names = {s.id: (s.name or s.label) for s in get_speakers(db, meeting_id)}
    lines = []
    for segment in segments:
        who = names.get(segment.speaker_id) if segment.speaker_id else None
        lines.append(f"{who}: {segment.text}" if who else segment.text)
    return "\n".join(lines)


async def _summarize(meeting_id: int, segments: list[Segment]) -> None:
    client = OllamaClient()
    transcript = _build_transcript(meeting_id, segments)
    title = await asyncio.to_thread(generate_title, client, transcript)
    result = await asyncio.to_thread(summarize, client, transcript)

    db = get_db()
    save_summary(
        db,
        meeting_id,
        summary=result.summary,
        key_points=result.key_points,
        action_items=result.action_items,
        decisions=result.decisions,
        open_questions=result.open_questions,
    )
    # Mirror the summary's action items into the cross-meeting hub table
    # (done-state carries over for unchanged texts).
    replace_action_items(db, meeting_id, result.action_items)
    if title:
        set_meeting_title(db, meeting_id, title)


async def run_postprocess(meeting_id: int, wav_path: str) -> None:
    """Diarize then summarize a finished meeting; always end in ``ready``."""
    db = get_db()
    segments = get_segments(db, meeting_id)
    if not segments:
        set_meeting_status(db, meeting_id, "ready")
        return

    try:
        await _diarize(meeting_id, wav_path, segments)
    except Exception:
        logger.exception("Diarization failed for meeting %d.", meeting_id)

    # Reload so the transcript carries the speaker attributions we just wrote.
    segments = get_segments(db, meeting_id)
    try:
        if get_settings().auto_summarize:
            await _summarize(meeting_id, segments)
    except OllamaUnavailable:
        logger.warning("Ollama unavailable — no summary for meeting %d.", meeting_id)
    except Exception:
        logger.exception("Summary failed for meeting %d.", meeting_id)

    try:
        # Lazy import keeps the embedder off the live-capture import path.
        import search_index

        await asyncio.to_thread(search_index.index_meeting, meeting_id)
    except Exception:
        logger.exception("Indexing failed for meeting %d.", meeting_id)

    set_meeting_status(db, meeting_id, "ready")
    logger.info("Post-processing complete for meeting %d.", meeting_id)


async def run_summary(meeting_id: int) -> None:
    """Re-generate just the summary (used by POST /summarize)."""
    segments = get_segments(get_db(), meeting_id)
    if not segments:
        return
    try:
        await _summarize(meeting_id, segments)
    except OllamaUnavailable:
        logger.warning("Ollama unavailable — no summary for meeting %d.", meeting_id)
    except Exception:
        logger.exception("Re-summary failed for meeting %d.", meeting_id)


def _track(task: asyncio.Task) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def schedule(meeting_id: int, wav_path: str) -> None:
    """Fire-and-forget full post-processing on the running event loop."""
    _track(asyncio.create_task(run_postprocess(meeting_id, wav_path)))


def schedule_summary(meeting_id: int) -> None:
    """Fire-and-forget summary regeneration on the running event loop."""
    _track(asyncio.create_task(run_summary(meeting_id)))
