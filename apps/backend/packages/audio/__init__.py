"""Audio capture package for MeetingMind.

Provides base and specialised classes for streaming audio from microphone
and system loopback (BlackHole) devices, plus a mixed mic + system capture.
"""

from packages.audio.capture import AudioCapture, MicrophoneCapture, SystemAudioCapture
from packages.audio.mixer import MixedAudioCapture

__all__ = [
    "AudioCapture",
    "MicrophoneCapture",
    "MixedAudioCapture",
    "SystemAudioCapture",
]