"""Audio capture package for MeetingMind.

Provides base and specialised classes for streaming audio from microphone
and system loopback (BlackHole) devices.
"""

from packages.audio.capture import AudioCapture, MicrophoneCapture, SystemAudioCapture

__all__ = ["AudioCapture", "MicrophoneCapture", "SystemAudioCapture"]
