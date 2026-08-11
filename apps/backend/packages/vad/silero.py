"""Streaming Silero VAD (v6, ONNX) — no torch, CPU-only.

The model file ships inside faster-whisper (a dependency already), so there
is nothing to download. Its path is resolved without importing faster-whisper
(which would pull in torch), keeping this package torch-free.
"""

from __future__ import annotations

import importlib.util
import logging
import os

import numpy as np
import onnxruntime

logger = logging.getLogger(__name__)

__all__ = ["SileroVAD"]


def _model_path() -> str:
    """Locate ``silero_vad_v6.onnx`` bundled with faster-whisper.

    Uses :func:`importlib.util.find_spec`, which locates the package without
    executing its ``__init__`` — so neither faster-whisper nor torch is
    imported just to read a file path.
    """
    spec = importlib.util.find_spec("faster_whisper")
    if spec is None or spec.origin is None:
        raise RuntimeError(
            "faster-whisper is not installed; its bundled silero_vad_v6.onnx "
            "is required for VAD."
        )
    path = os.path.join(os.path.dirname(spec.origin), "assets", "silero_vad_v6.onnx")
    if not os.path.exists(path):
        raise RuntimeError(f"Silero VAD model not found at {path}.")
    return path


class SileroVAD:
    """Streaming voice-activity detector over 16 kHz mono float32 audio.

    Wraps the Silero VAD v6 ONNX model for *streaming* use: the LSTM state
    (``h``, ``c``) and the 64-sample context window persist across calls, so
    feeding consecutive blocks is equivalent to running the model over the
    whole stream. Pure onnxruntime — no torch at import or runtime.

    The model consumes fixed 512-sample windows (32 ms at 16 kHz). Chunks of
    any length are accepted; leftover samples that don't fill a window are
    buffered for the next call. Capture blocks are 1024 samples = exactly two
    windows, so nothing is buffered in the common case.
    """

    SAMPLE_RATE: int = 16_000
    WINDOW_SAMPLES: int = 512
    CONTEXT_SAMPLES: int = 64

    def __init__(self, threshold: float = 0.5) -> None:
        """Load the ONNX session.

        Args:
            threshold: Probability at or above which :meth:`is_speech` is True.
        """
        self.threshold = threshold

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.enable_cpu_mem_arena = False
        opts.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            _model_path(),
            providers=["CPUExecutionProvider"],
            sess_options=opts,
        )
        self.reset()
        logger.info("SileroVAD loaded (threshold=%.2f).", threshold)

    def reset(self) -> None:
        """Clear streaming state — call between independent recordings."""
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT_SAMPLES), dtype=np.float32)
        self._buffer = np.empty(0, dtype=np.float32)
        self._last_prob = 0.0

    def confidence(self, chunk: np.ndarray) -> float:
        """Advance the model over ``chunk`` and return a speech probability.

        Processes every complete 512-sample window (plus any buffered
        remainder) and returns the **maximum** probability among them — the
        most responsive choice for catching speech onset. If ``chunk`` does
        not complete a window, the last known probability is returned and the
        samples are buffered for next time.

        This is the single state-advancing call; :meth:`is_speech` delegates
        to it, so call exactly one of the two per chunk.

        Args:
            chunk: 1-D or ``(N, 1)`` float32 audio in [-1, 1] at 16 kHz.
        """
        samples = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if self._buffer.size:
            samples = np.concatenate([self._buffer, samples])

        win = self.WINDOW_SAMPLES
        n_windows = samples.size // win
        if n_windows == 0:
            self._buffer = samples
            return self._last_prob

        probs = []
        for i in range(n_windows):
            window = samples[i * win : (i + 1) * win].reshape(1, win)
            inp = np.concatenate([self._context, window], axis=1)  # (1, 576)
            out, self._h, self._c = self._session.run(
                None, {"input": inp, "h": self._h, "c": self._c}
            )
            self._context = window[:, -self.CONTEXT_SAMPLES :]
            probs.append(float(out.reshape(-1)[0]))

        self._buffer = samples[n_windows * win :].copy()
        self._last_prob = max(probs)
        return self._last_prob

    def is_speech(self, chunk: np.ndarray) -> bool:
        """True if ``chunk``'s speech probability meets the threshold."""
        return self.confidence(chunk) >= self.threshold
