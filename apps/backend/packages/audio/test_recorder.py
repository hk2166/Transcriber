"""Unit tests for SessionRecorder (no audio hardware required)."""

import numpy as np
import soundfile as sf

from packages.audio.recorder import SessionRecorder


def make_block(value: float, frames: int = 1024) -> np.ndarray:
    return np.full((frames, 1), value, dtype=np.float32)


def test_writes_all_blocks_in_order(tmp_path):
    path = tmp_path / "session.wav"
    with SessionRecorder(path) as recorder:
        for value in (0.1, -0.2, 0.3):
            recorder.write(make_block(value))

    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    assert sample_rate == SessionRecorder.SAMPLE_RATE
    assert audio.shape == (3 * 1024, 1)
    assert np.allclose(audio[:1024], 0.1, atol=1e-3)
    assert np.allclose(audio[1024:2048], -0.2, atol=1e-3)
    assert np.allclose(audio[2048:], 0.3, atol=1e-3)
    assert recorder.frames_written == 3 * 1024


def test_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "deep" / "nested" / "session.wav"
    with SessionRecorder(path) as recorder:
        recorder.write(make_block(0.5))
    assert path.exists()


def test_write_after_close_is_dropped(tmp_path):
    path = tmp_path / "session.wav"
    recorder = SessionRecorder(path)
    recorder.start()
    recorder.write(make_block(0.1))
    recorder.close()
    recorder.write(make_block(0.9))  # must neither raise nor touch the file

    audio, _ = sf.read(path, dtype="float32", always_2d=True)
    assert len(audio) == 1024
    assert recorder.duration_seconds == 1024 / SessionRecorder.SAMPLE_RATE


def test_close_is_idempotent(tmp_path):
    recorder = SessionRecorder(tmp_path / "session.wav")
    recorder.start()
    recorder.close()
    recorder.close()


def test_close_without_start_creates_nothing(tmp_path):
    recorder = SessionRecorder(tmp_path / "session.wav")
    recorder.close()
    assert not (tmp_path / "session.wav").exists()