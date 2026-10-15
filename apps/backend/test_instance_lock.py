"""Single-instance lock + the frozen entry point's freeze_support guard.

Regression for 2026-10-15: the frozen backend, re-executed as multiprocessing's
resource tracker, booted a whole second backend that re-processed the
interrupted meeting and spawned the next — a chain that reset the Mac.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import instance_lock

HERE = Path(__file__).parent


def test_second_acquire_is_refused_until_release(tmp_path: Path) -> None:
    lock = tmp_path / "backend.lock"
    fd = instance_lock.acquire(lock)
    assert lock.read_text() == str(os.getpid())
    with pytest.raises(instance_lock.AnotherInstanceRunning):
        instance_lock.acquire(lock, timeout_s=0.2)
    instance_lock.release(fd)
    instance_lock.release(instance_lock.acquire(lock, timeout_s=0.2))


def test_lock_held_by_another_process_and_freed_when_it_dies(tmp_path: Path) -> None:
    lock = tmp_path / "backend.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                sys.path.insert(0, {str(HERE)!r})
                import instance_lock
                instance_lock.acquire(__import__("pathlib").Path({str(lock)!r}))
                print("held", flush=True)
                time.sleep(60)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(instance_lock.AnotherInstanceRunning):
            instance_lock.acquire(lock, timeout_s=0.2)
        # A crash (no clean release) must not leave the lock stuck.
        holder.send_signal(signal.SIGKILL)
        holder.wait(timeout=5)
        instance_lock.release(instance_lock.acquire(lock, timeout_s=2))
    finally:
        if holder.poll() is None:
            holder.kill()


def test_backend_exits_when_its_launcher_dies() -> None:
    """A force-quit app must not leave its backend holding the lock."""
    launcher = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import os, subprocess, sys
                child = subprocess.Popen([sys.executable, "-c", (
                    "import asyncio, sys; sys.path.insert(0, {str(HERE)!r}); "
                    "import instance_lock; "
                    "asyncio.run(instance_lock.exit_when_orphaned(poll_s=0.1)); "
                    "import time; time.sleep(60)"
                )], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(child.pid, flush=True)
                os._exit(0)  # die without stopping the child, like a force-quit
                """
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    orphan = int(launcher.stdout.strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(orphan, 0)
        except ProcessLookupError:
            return  # gone — it shut itself down
        time.sleep(0.1)
    os.kill(orphan, signal.SIGKILL)
    pytest.fail("orphaned backend kept running after its launcher died")


def test_frozen_entry_calls_freeze_support_before_heavy_imports() -> None:
    tree = ast.parse((HERE / "server_main.py").read_text())
    first_freeze = first_main_import = None
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.If) and "freeze_support" in ast.unparse(node):
            first_freeze = first_freeze if first_freeze is not None else i
        if isinstance(node, ast.ImportFrom) and node.module == "main":
            first_main_import = i
        if isinstance(node, ast.Import) and any(a.name == "uvicorn" for a in node.names):
            first_main_import = first_main_import if first_main_import is not None else i
    assert first_freeze is not None, "server_main.py must call multiprocessing.freeze_support()"
    assert first_main_import is not None
    assert first_freeze < first_main_import, "freeze_support() must run before uvicorn/main import"
