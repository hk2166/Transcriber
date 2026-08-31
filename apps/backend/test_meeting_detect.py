"""Meeting-detection state machine (no CoreAudio / process I/O)."""

import meeting_detect
from meeting_detect import _step


def reset():
    meeting_detect._state.update(app=None, since=None, source=None)
    meeting_detect._mic_streak = 0


def test_named_app_detects_instantly():
    reset()
    _step(recording=False, named="Zoom", mic=False)
    state = meeting_detect.current()
    assert (state["app"], state["source"]) == ("Zoom", "app")
    assert state["since"] is not None


def test_mic_signal_is_debounced():
    reset()
    _step(recording=False, named=None, mic=True)
    assert meeting_detect.current()["app"] is None  # one poll isn't enough
    _step(recording=False, named=None, mic=True)
    state = meeting_detect.current()
    assert (state["app"], state["source"]) == ("Meeting", "microphone")


def test_mic_blip_resets_streak():
    reset()
    _step(recording=False, named=None, mic=True)
    _step(recording=False, named=None, mic=False)  # released — dictation blip
    _step(recording=False, named=None, mic=True)
    assert meeting_detect.current()["app"] is None


def test_our_own_recording_never_triggers():
    reset()
    _step(recording=False, named=None, mic=True)
    _step(recording=True, named=None, mic=True)  # Confab started capturing
    assert meeting_detect.current()["app"] is None
    _step(recording=True, named="Zoom", mic=True)  # even a named app stands down
    assert meeting_detect.current()["app"] is None


def test_episode_clears_when_call_ends():
    reset()
    _step(recording=False, named="Zoom", mic=False)
    first_since = meeting_detect.current()["since"]
    _step(recording=False, named=None, mic=False)
    assert meeting_detect.current()["app"] is None
    _step(recording=False, named="Zoom", mic=False)
    assert meeting_detect.current()["since"] != first_since  # new episode


def test_named_beats_generic_mic():
    reset()
    _step(recording=False, named=None, mic=True)
    _step(recording=False, named="Webex", mic=True)
    state = meeting_detect.current()
    assert (state["app"], state["source"]) == ("Webex", "app")
