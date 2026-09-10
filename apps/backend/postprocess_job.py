"""Post-meeting processing: diarize speakers, then summarize with the local LLM.

Runs in the background after a session ends. Each stage degrades gracefully —
diarization needs torch, summaries need Ollama, and the app must still work
(and reach ``ready``) when either is missing.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading

import model_gate
from database import get_db
from packages.diarization import SpeakerDiarizer, assign_speaker
from packages.intelligence import (
    OllamaUnavailable,
    generate_title,
    summarize,
)
from packages.storage import (
    Segment,
    create_speakers,
    get_meeting,
    get_meetings,
    get_segments,
    get_speakers,
    replace_action_items,
    replace_segments,
    save_summary,
    set_meeting_status,
    set_meeting_title,
    set_segment_speaker,
)
from settings import get_settings

logger = logging.getLogger(__name__)

_diarizer: SpeakerDiarizer | None = None
_diarizer_lock = threading.Lock()
_refine_transcriber = None  # WhisperTranscriber, loaded on first refine
_refine_model_size: str | None = None
_refine_lock = threading.Lock()
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


def _get_refine_transcriber(model_size: str):
    """A Whisper model dedicated to the refine pass, cached and rebuilt only
    when the configured refine model changes. Kept separate from the live
    transcriber so the two can be different sizes (fast live, accurate refine)."""
    from packages.transcription import WhisperTranscriber

    global _refine_transcriber, _refine_model_size
    with _refine_lock:
        if _refine_transcriber is None or _refine_model_size != model_size:
            _refine_transcriber = WhisperTranscriber(model_size=model_size)
            _refine_model_size = model_size
    return _refine_transcriber


def _release_refine_transcriber() -> None:
    """Drop the refine Whisper so it isn't resident while the next model loads.

    faster-whisper (CTranslate2) returns this memory to the OS on release —
    unlike PyTorch — so freeing the refine pass's ~0.5-3 GB before the diarizer
    loads is a real co-residency win on low-memory machines."""
    global _refine_transcriber, _refine_model_size
    with _refine_lock:
        _refine_transcriber = None
        _refine_model_size = None
    gc.collect()


async def _refine(meeting_id: int, wav_path: str) -> bool:
    """Re-transcribe the whole recording and replace the live segments.

    The live path emits rough, VAD-chopped, greedily-decoded text for instant
    feedback; here we run the full audio through beam search with cross-segment
    context for a markedly cleaner transcript. Best-effort: on any failure the
    live segments are left untouched. Returns whether segments were replaced.
    """
    import os

    if not wav_path or not os.path.exists(wav_path):
        logger.warning("No recording for meeting %d — skipping refine.", meeting_id)
        return False
    settings = get_settings()
    transcriber = await asyncio.to_thread(
        _get_refine_transcriber, settings.refine_model
    )
    segments = await asyncio.to_thread(transcriber.transcribe_file, wav_path)
    if not segments:
        logger.warning(
            "Refine produced no segments for meeting %d — keeping live transcript.",
            meeting_id,
        )
        return False
    count = replace_segments(get_db(), meeting_id, segments)
    logger.info(
        "Refined meeting %d: %d segments (whisper-%s).",
        meeting_id,
        count,
        settings.refine_model,
    )
    return True


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
    import llm

    client = llm.current_client()
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


async def _process_segments(meeting_id: int, wav_path: str) -> None:
    """Diarize → summarize → index a meeting that already has segments.

    Shared by the recording pipeline (after the refine pass) and the import
    pipeline (after the initial transcription). Each stage degrades on its own.
    Runs inside a held model slot.
    """
    db = get_db()
    try:
        await _diarize(meeting_id, wav_path, get_segments(db, meeting_id))
    except Exception:
        logger.exception("Diarization failed for meeting %d.", meeting_id)
    # The diarizer is deliberately NOT released here: in dev it's PyTorch,
    # whose allocator never returns RSS to the OS (measured), so releasing
    # only forces a costly reload; in the packaged app diarization runs in a
    # subprocess that frees on exit anyway.

    # Reload so the transcript carries the speaker attributions just written.
    segments = get_segments(db, meeting_id)
    try:
        if get_settings().auto_summarize:
            await _summarize(meeting_id, segments)
    except OllamaUnavailable:
        logger.warning("Ollama unavailable — no summary for meeting %d.", meeting_id)
    except Exception:
        logger.exception("Summary failed for meeting %d.", meeting_id)

    # Lazy import keeps the embedder off the live-capture import path.
    import search_index

    try:
        await asyncio.to_thread(search_index.index_meeting, meeting_id)
    except Exception:
        logger.exception("Indexing failed for meeting %d.", meeting_id)
    finally:
        await asyncio.to_thread(search_index.release_embedder)


async def _finalize(meeting_id: int) -> None:
    """Link calendar attendees, propose sync items, and mark ``ready``."""
    await _link_calendar_attendees(meeting_id)
    await _propose_sync(meeting_id)
    set_meeting_status(get_db(), meeting_id, "ready")


async def run_postprocess(meeting_id: int, wav_path: str) -> None:
    """Diarize then summarize a finished meeting; always end in ``ready``."""
    db = get_db()
    if not get_segments(db, meeting_id):
        set_meeting_status(db, meeting_id, "ready")
        return

    # Everything below loads heavy models (refine Whisper, diarizer, embedder).
    # Hold one model slot so concurrent post-processing jobs — e.g. the startup
    # reconciliation resuming a backlog — run one at a time instead of loading
    # every model at once and exhausting memory.
    async with model_gate.slot(f"postprocess:{meeting_id}"):
        # Re-transcribe the whole recording for a cleaner transcript, then
        # diarize the *refined* text. Runs first so everything builds on it.
        if get_settings().refine_transcript:
            try:
                await _refine(meeting_id, wav_path)
            except Exception:
                logger.exception("Transcript refine failed for meeting %d.", meeting_id)
            finally:
                # Free the refine Whisper before the diarizer loads on top of it.
                await asyncio.to_thread(_release_refine_transcriber)
        await _process_segments(meeting_id, wav_path)

    await _finalize(meeting_id)
    logger.info("Post-processing complete for meeting %d.", meeting_id)


async def _transcribe_import(meeting_id: int, wav_path: str) -> bool:
    """Transcribe an imported file into the meeting's segments (mandatory).

    Unlike the recording path there is no live transcript to refine — this IS
    the transcript. Uses the same full-file beam-search pass. Returns whether
    any segments were written.
    """
    import os

    if not wav_path or not os.path.exists(wav_path):
        logger.warning("No audio for import %d — nothing to transcribe.", meeting_id)
        return False
    transcriber = await asyncio.to_thread(
        _get_refine_transcriber, get_settings().refine_model
    )
    segments = await asyncio.to_thread(transcriber.transcribe_file, wav_path)
    if not segments:
        return False
    count = replace_segments(get_db(), meeting_id, segments)
    logger.info("Imported meeting %d: transcribed %d segments.", meeting_id, count)
    return True


async def run_import(meeting_id: int, wav_path: str) -> None:
    """Process an uploaded audio/video file: transcribe → diarize → summarize
    → index → propose → ready. Mirrors run_postprocess but transcribes first."""
    async with model_gate.slot(f"import:{meeting_id}"):
        try:
            transcribed = await _transcribe_import(meeting_id, wav_path)
        except Exception:
            logger.exception("Import transcription failed for meeting %d.", meeting_id)
            transcribed = False
        finally:
            await asyncio.to_thread(_release_refine_transcriber)
        if transcribed:
            await _process_segments(meeting_id, wav_path)

    await _finalize(meeting_id)
    logger.info("Import processing complete for meeting %d.", meeting_id)


async def _link_calendar_attendees(meeting_id: int) -> None:
    """Match the recording to its calendar event and link attendees as People.

    Best-effort like every other stage: no Google connected → silent skip;
    any other failure is logged and never blocks ``ready``. No models load
    here, so it runs outside the model gate.
    """
    from datetime import datetime, timedelta

    import google_calendar
    import google_service
    from packages.integrations.google_oauth import GoogleAuthError

    try:
        meeting = get_meeting(get_db(), meeting_id)
        if meeting is None:
            return
        started = datetime.fromisoformat(meeting.started_at)
        ended = (
            datetime.fromisoformat(meeting.ended_at)
            if meeting.ended_at
            else started + timedelta(hours=1)
        )
        events = await asyncio.to_thread(
            google_calendar.fetch_events,
            started - timedelta(hours=2),
            ended + timedelta(hours=2),
        )
        event = google_calendar.best_match(events, started, ended)
        if event is None:
            logger.info("Meeting %d: no unambiguous calendar match.", meeting_id)
            return
        self_email = google_service.status().get("email")
        linked = await asyncio.to_thread(
            google_calendar.ingest_attendees,
            get_db(), meeting_id, event, self_email,
        )
        logger.info(
            "Meeting %d: matched calendar event %r — linked %d attendee(s).",
            meeting_id, event.title, linked,
        )
    except GoogleAuthError:
        logger.debug("Meeting %d: Google not connected — skipping calendar link.",
                     meeting_id)
    except Exception:
        logger.exception("Calendar attendee link failed for meeting %d.", meeting_id)


async def _propose_sync(meeting_id: int) -> None:
    """Generate cross-app sync proposals (local only; best-effort)."""
    try:
        import proposal_service

        await asyncio.to_thread(proposal_service.propose_for_meeting, meeting_id)
    except Exception:
        logger.exception("Sync proposals failed for meeting %d.", meeting_id)


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
    # Fresh summary ⇒ fresh proposals (old un-applied ones go stale).
    await _propose_sync(meeting_id)


def _track(task: asyncio.Task) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def reconcile_interrupted_meetings() -> None:
    """Recover meetings a crash or force-quit left stuck in ``recording`` /
    ``processing``. Runs once at startup.

    Without this, a meeting interrupted before it reached ``ready`` hangs in that
    status forever with no path back. Here each stranded meeting is brought to a
    usable terminal state: if a recording with captured segments survives, re-run
    post-processing to finish it properly (refine → diarize → summarize); if
    there's nothing recoverable, mark it ``ready`` so it at least stops hanging.
    """
    import os

    db = get_db()
    stuck = [m for m in get_meetings(db) if m.status in ("recording", "processing")]
    if not stuck:
        return
    logger.info("Reconciling %d interrupted meeting(s) from a previous run.", len(stuck))
    for m in stuck:
        if m.wav_path and os.path.exists(m.wav_path) and m.segment_count > 0:
            set_meeting_status(db, m.id, "processing")
            schedule(m.id, m.wav_path)  # refine → diarize → summarize → ready
            logger.info("Meeting %d: resuming post-processing.", m.id)
        else:
            set_meeting_status(db, m.id, "ready")  # nothing to finish — unhang it
            logger.info("Meeting %d: no recoverable audio — marked ready.", m.id)


def schedule(meeting_id: int, wav_path: str) -> None:
    """Fire-and-forget full post-processing on the running event loop."""
    _track(asyncio.create_task(run_postprocess(meeting_id, wav_path)))


def schedule_import(meeting_id: int, wav_path: str) -> None:
    """Fire-and-forget import processing (transcribe → … → ready)."""
    _track(asyncio.create_task(run_import(meeting_id, wav_path)))


def schedule_summary(meeting_id: int) -> None:
    """Fire-and-forget summary regeneration on the running event loop."""
    _track(asyncio.create_task(run_summary(meeting_id)))
