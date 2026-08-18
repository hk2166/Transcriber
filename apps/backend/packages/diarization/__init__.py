"""Speaker diarization for MeetingMind (pyannote, post-meeting).

Importing this package is torch-free; only constructing a ``SpeakerDiarizer``
loads torch/pyannote.
"""

from packages.diarization.diarizer import SpeakerDiarizer, SpeakerTurn
from packages.diarization.merger import assign_speaker, assign_speakers

__all__ = [
    "SpeakerDiarizer",
    "SpeakerTurn",
    "assign_speaker",
    "assign_speakers",
]
