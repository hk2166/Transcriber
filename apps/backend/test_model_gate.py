"""The model gate must let only one heavy job run at a time."""

from __future__ import annotations

import asyncio

import model_gate


def test_gate_serializes_concurrent_jobs():
    """Five jobs launched at once run one-at-a-time: active never exceeds 1,
    and each job's enter/exit never interleaves with another's."""
    max_active = 0
    log: list[tuple[str, str]] = []

    async def job(name: str) -> None:
        nonlocal max_active
        async with model_gate.slot(name):
            log.append(("enter", name))
            max_active = max(max_active, model_gate.active())
            await asyncio.sleep(0.01)  # hold the slot so overlap would show
            log.append(("exit", name))

    async def main() -> None:
        await asyncio.gather(*(job(f"j{i}") for i in range(5)))

    asyncio.run(main())

    assert max_active == 1, f"gate allowed {max_active} concurrent jobs"
    assert len(log) == 10
    # Each enter is immediately followed by the SAME job's exit — no interleave.
    for i in range(0, len(log), 2):
        assert log[i][0] == "enter"
        assert log[i + 1] == ("exit", log[i][1])
    # Counters return to zero once everything drains.
    assert model_gate.active() == 0
    assert model_gate.waiting() == 0


def test_gate_reports_waiting_jobs():
    """While one job holds the slot, a second reports as waiting."""
    seen_waiting = 0

    async def holder(started: asyncio.Event, release: asyncio.Event) -> None:
        async with model_gate.slot("holder"):
            started.set()
            await release.wait()

    async def main() -> None:
        nonlocal seen_waiting
        started, release = asyncio.Event(), asyncio.Event()
        h = asyncio.create_task(holder(started, release))
        await started.wait()  # holder now owns the only slot

        async def waiter() -> None:
            async with model_gate.slot("waiter"):
                pass

        w = asyncio.create_task(waiter())
        await asyncio.sleep(0.01)  # let the waiter block on acquire
        seen_waiting = model_gate.waiting()
        release.set()
        await asyncio.gather(h, w)

    asyncio.run(main())
    assert seen_waiting == 1
