"""Post-meeting speaker diarization — runs in the background after a session ends.

torch-heavy, so it runs off the event loop via ``asyncio.to_thread`` and never
touches the live path. If torch/pyannote are unavailable (e.g. the Phase-1
packaged binary excludes torch), it degrades gracefully: the meeting is still
marked ``ready``, just without speaker labels.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from database import get_db
from packages.diarization import SpeakerDiarizer, assign_speaker
from packages.storage import (
    create_speakers,
    get_segments,
    set_meeting_status,
    set_segment_speaker,
)

logger = logging.getLogger(__name__)

_diarizer: SpeakerDiarizer | None = None
_diarizer_lock = threading.Lock()

#: Keep references so fire-and-forget tasks aren't garbage-collected mid-run.
_tasks: set[asyncio.Task] = set()


def get_diarizer() -> SpeakerDiarizer:
    """Load the pyannote pipeline once (blocking — call via ``to_thread``)."""
    global _diarizer
    with _diarizer_lock:
        if _diarizer is None:
            _diarizer = SpeakerDiarizer()
    return _diarizer


async def run_diarization(meeting_id: int, wav_path: str) -> None:
    """Diarize the WAV, attribute segments to speakers, mark the meeting ready."""
    db = get_db()
    try:
        segments = get_segments(db, meeting_id)
        if not segments:
            set_meeting_status(db, meeting_id, "ready")
            return

        diarizer = await asyncio.to_thread(get_diarizer)
        turns = await asyncio.to_thread(diarizer.diarize_file, wav_path)

        labels = [turn.speaker for turn in turns]
        if labels:
            mapping = create_speakers(db, meeting_id, labels)
            for segment in segments:
                label = assign_speaker(segment.start_ms, segment.end_ms, turns)
                if label is not None:
                    set_segment_speaker(db, segment.id, mapping[label])

        set_meeting_status(db, meeting_id, "ready")
        logger.info(
            "Diarization complete for meeting %d (%d speakers).",
            meeting_id,
            len(set(labels)),
        )
    except Exception:
        logger.exception(
            "Diarization failed for meeting %d — marking ready without speakers.",
            meeting_id,
        )
        set_meeting_status(db, meeting_id, "ready")


def schedule(meeting_id: int, wav_path: str) -> None:
    """Fire-and-forget the diarization job on the running event loop."""
    task = asyncio.create_task(run_diarization(meeting_id, wav_path))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
