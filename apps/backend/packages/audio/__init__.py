"""Audio capture package for Confab.

Provides base and specialised classes for streaming audio from microphone
and system loopback (BlackHole) devices, a mixed mic + system capture, and
a non-blocking WAV session recorder.
"""

from packages.audio.capture import AudioCapture, MicrophoneCapture, SystemAudioCapture
from packages.audio.mixer import MixedAudioCapture
from packages.audio.recorder import SessionRecorder, default_recordings_dir
from packages.audio import routing

__all__ = [
    "routing",
    "AudioCapture",
    "MicrophoneCapture",
    "MixedAudioCapture",
    "SessionRecorder",
    "SystemAudioCapture",
    "default_recordings_dir",
]
