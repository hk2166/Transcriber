"""LLM API keys live in the Keychain; settings.json holds only a sentinel.

The ``security`` CLI is faked at the subprocess boundary (same spirit as the
google_service tests), so keychain.py's real command construction and output
parsing are exercised without touching the developer's actual Keychain.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

import keychain
import settings as settings_module
from settings import (
    KEY_SENTINEL,
    LLM_KEYCHAIN_SERVICE,
    Settings,
    get_settings,
    resolve_api_key,
    save_settings,
)


class FakeSecurity:
    """In-memory stand-in for the macOS ``security`` CLI."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.fail = False  # simulate a locked/refusing keychain

    def __call__(self, argv, **kwargs):
        cmd = argv[1]

        def arg(flag):
            return argv[argv.index(flag) + 1] if flag in argv else None

        key = (arg("-s"), arg("-a"))
        if cmd == "add-generic-password":
            if self.fail:
                raise subprocess.CalledProcessError(1, argv)
            self.store[key] = arg("-w")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd == "find-generic-password":
            value = self.store.get(key)
            return SimpleNamespace(
                returncode=0 if value is not None else 44,
                stdout=f"{value}\n" if value is not None else "",
                stderr="",
            )
        if cmd == "delete-generic-password":
            self.store.pop(key, None)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected security command: {argv}")


@pytest.fixture
def security(monkeypatch):
    fake = FakeSecurity()
    monkeypatch.setattr(keychain.subprocess, "run", fake)
    return fake


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point the settings store at a temp file; never touch the real one."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_module, "_path", lambda: path)
    settings_module.reset_cache()
    yield path
    settings_module.reset_cache()


def test_keychain_set_get_delete_roundtrip(security):
    assert keychain.set_secret("svc", "acct", "hunter2") is True
    assert keychain.get_secret("svc", "acct") == "hunter2"
    keychain.delete_secret("svc", "acct")
    assert keychain.get_secret("svc", "acct") is None


def test_save_moves_raw_key_to_keychain_never_disk(security, isolated_settings):
    save_settings(Settings(api_keys={"openai": "sk-raw-123"}))

    text = isolated_settings.read_text()
    assert "sk-raw-123" not in text  # raw key never persisted to disk
    assert json.loads(text)["api_keys"]["openai"] == KEY_SENTINEL
    assert security.store[(LLM_KEYCHAIN_SERVICE, "openai")] == "sk-raw-123"
    assert resolve_api_key(get_settings(), "openai") == "sk-raw-123"


def test_sentinel_and_blank_mean_unchanged(security):
    save_settings(Settings(api_keys={"openai": "sk-raw-123"}))

    # GET returns the sentinel; PUTting it back must not clobber the key.
    save_settings(Settings(api_keys={"openai": KEY_SENTINEL}))
    assert resolve_api_key(get_settings(), "openai") == "sk-raw-123"
    # A blank password field likewise leaves the stored key alone.
    save_settings(Settings(api_keys={"openai": ""}))
    assert resolve_api_key(get_settings(), "openai") == "sk-raw-123"
    # Typing a new value replaces it.
    save_settings(Settings(api_keys={"openai": "sk-new-456"}))
    assert resolve_api_key(get_settings(), "openai") == "sk-new-456"
    assert security.store[(LLM_KEYCHAIN_SERVICE, "openai")] == "sk-new-456"


def test_first_load_migrates_plaintext_keys(security, isolated_settings):
    # A pre-Keychain settings.json with a raw key on disk.
    isolated_settings.write_text(
        Settings(api_keys={"anthropic": "sk-ant-legacy"}).model_dump_json()
    )

    loaded = get_settings()

    assert loaded.api_keys["anthropic"] == KEY_SENTINEL
    assert "sk-ant-legacy" not in isolated_settings.read_text()  # rewritten
    assert security.store[(LLM_KEYCHAIN_SERVICE, "anthropic")] == "sk-ant-legacy"
    assert resolve_api_key(loaded, "anthropic") == "sk-ant-legacy"


def test_keychain_refusal_falls_back_to_plaintext(security, isolated_settings):
    security.fail = True
    save_settings(Settings(api_keys={"groq": "gsk-raw"}))

    # Graceful fallback: the key still works, stored raw in the 600-file.
    assert json.loads(isolated_settings.read_text())["api_keys"]["groq"] == "gsk-raw"
    assert resolve_api_key(get_settings(), "groq") == "gsk-raw"


def test_google_fallback_entries_pass_through(security, isolated_settings):
    # google_service's keychain-failure fallback writes _google_* entries raw;
    # the LLM key plumbing must not intercept them.
    save_settings(Settings(api_keys={"_google_refresh_token": "rt-raw"}))

    stored = json.loads(isolated_settings.read_text())["api_keys"]
    assert stored["_google_refresh_token"] == "rt-raw"
    assert (LLM_KEYCHAIN_SERVICE, "_google_refresh_token") not in security.store


def test_api_responses_only_reveal_presence(security):
    from routers.settings import _redacted

    save_settings(Settings(api_keys={"openai": "sk-raw-123", "mistral": ""}))
    exposed = _redacted(get_settings()).api_keys
    assert exposed == {"openai": KEY_SENTINEL, "mistral": ""}
    # And a raw legacy value (keychain refused) is masked too.
    security.fail = True
    save_settings(Settings(api_keys={"groq": "gsk-raw"}))
    assert _redacted(get_settings()).api_keys["groq"] == KEY_SENTINEL
