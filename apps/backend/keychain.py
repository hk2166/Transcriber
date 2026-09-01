"""macOS Keychain access via the built-in ``security`` CLI.

Shared by every secret Confab stores off-disk (Google OAuth tokens, LLM
provider API keys). No dependency, no daemon: each call shells out to
``security`` with a (service, account) pair. All failures are swallowed into
``False``/``None`` so callers can fall back gracefully (e.g. to the chmod-600
settings store) and the app keeps working headless or on a locked keychain.
"""

from __future__ import annotations

import subprocess

__all__ = ["delete_secret", "get_secret", "set_secret"]


def set_secret(service: str, account: str, value: str) -> bool:
    """Store (or update, via ``-U``) a secret; False if the Keychain refused."""
    try:
        subprocess.run(
            ["security", "add-generic-password", "-U", "-s", service,
             "-a", account, "-w", value],
            capture_output=True, check=True, timeout=10,
        )
        return True
    except Exception:
        return False


def get_secret(service: str, account: str) -> str | None:
    """Read a secret, or ``None`` if absent/unreadable."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def delete_secret(service: str, account: str) -> None:
    """Remove a secret (quietly a no-op if it doesn't exist)."""
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", service, "-a", account],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass
