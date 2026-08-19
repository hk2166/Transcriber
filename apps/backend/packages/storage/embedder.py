"""Torch-free sentence embeddings — all-MiniLM-L6-v2 via ONNX + onnxruntime.

Deliberately not sentence-transformers: that pulls torch (and, here, a broken
torchcodec), and the packaged app is torch-free (see PACKAGING.md). This uses
the ONNX export of the same model with the already-bundled onnxruntime, so
search ships in the sidecar binary too. Model + tokenizer download once from
Hugging Face to the HF cache.
"""

from __future__ import annotations

import logging

import numpy as np
import onnxruntime
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

logger = logging.getLogger(__name__)

__all__ = ["Embedder"]


class Embedder:
    """Encodes text to L2-normalised 384-d vectors (cosine == dot product)."""

    REPO = "sentence-transformers/all-MiniLM-L6-v2"
    DIM = 384
    MAX_TOKENS = 256

    def __init__(self) -> None:
        onnx_path = hf_hub_download(self.REPO, "onnx/model.onnx")
        tokenizer_path = hf_hub_download(self.REPO, "tokenizer.json")

        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_padding()
        self._tokenizer.enable_truncation(max_length=self.MAX_TOKENS)

        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            onnx_path, providers=["CPUExecutionProvider"], sess_options=opts
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        logger.info("Embedder loaded (all-MiniLM-L6-v2 ONNX, dim=%d).", self.DIM)

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return an ``(len(texts), 384)`` float32 array of unit vectors."""
        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32)

        encodings = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        feed = {"input_ids": input_ids, "attention_mask": attention}
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.zeros_like(input_ids)

        tokens = self._session.run(None, feed)[0]  # (N, T, 384)

        # Mean-pool over real tokens, then L2-normalise.
        mask = attention[:, :, None].astype(np.float32)
        summed = (tokens * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        pooled = summed / counts
        norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)
        return (pooled / norms).astype(np.float32)

    def encode_one(self, text: str) -> np.ndarray:
        """Encode a single string to a ``(384,)`` unit vector."""
        return self.encode([text])[0]
