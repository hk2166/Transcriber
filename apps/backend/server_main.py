"""Frozen entry point for the packaged backend (PyInstaller → Tauri sidecar).

Binds a free localhost port, announces it on stdout so the Tauri host can read
it (the frontend then talks to that port instead of a hardcoded one), and runs
the FastAPI app.
"""

from __future__ import annotations

import os

# The Xet native accelerator (hf_xet) is not bundled — it's an optional
# huggingface_hub download optimisation with an automatic HTTP fallback.
# Disable it before anything imports huggingface_hub so it never probes for
# the missing lib.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import socket  # noqa: E402

import uvicorn  # noqa: E402

from main import app  # noqa: E402


def _free_port() -> int:
    """Pick an OS-assigned free port on localhost.

    Small TOCTOU window between choosing and uvicorn binding — acceptable for a
    single-user desktop app; revisit if it ever races (Day 16).
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def main() -> None:
    port = _free_port()
    # Handshake line the Tauri host greps for on the sidecar's stdout.
    print(f"CONFAB_PORT={port}", flush=True)
    # Bound the graceful-shutdown wait so an open recording WebSocket can't stall
    # SIGTERM: uvicorn force-closes lingering connections after this and then runs
    # the lifespan shutdown (which finalizes an in-progress recording) — all well
    # inside the host's SIGTERM→SIGKILL window.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
