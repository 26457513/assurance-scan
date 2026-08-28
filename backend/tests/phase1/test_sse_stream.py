"""FR-SSE-STREAM tests.

The /api/scans/{run_id}/stream endpoint is a thin wrapper around the in-memory
event bus (app.events.bus). These tests exercise the bus directly:

- publish then subscribe sees the event
- subscriber added BEFORE publish receives it live
- subscriber added AFTER publish with after_id replays buffered events
- buffer capacity (1000) trims oldest events beyond the soft bound
- drop(run_id) clears the run's buffer and subscribers
"""
from __future__ import annotations

import asyncio

import pytest

from app.events import EventBus


@pytest.fixture
def bus():
    return EventBus()


# ---------------------------------------------------------------------------
# Live publishing
# ---------------------------------------------------------------------------

async def test_subscriber_receives_live_published_event(bus) -> None:
    """Subscribe, then publish — subscriber queue gets the event."""
    q = await bus.subscribe("run-1")
    eid = bus.publish("run-1", "scanner_started", {"scanner": "semgrep"})

    eid_recv, kind, payload = await asyncio.wait_for(q.get(), timeout=0.5)
    assert eid_recv == eid
    assert kind == "scanner_started"
    assert payload == {"scanner": "semgrep"}


async def test_event_id_is_monotonic_per_run(bus) -> None:
    """Event IDs within a run increment by 1 each publish."""
    await bus.subscribe("r")
    e1 = bus.publish("r", "scan_started", {})
    e2 = bus.publish("r", "scanner_started", {})
    e3 = bus.publish("r", "scan_completed", {})
    assert (e2 - e1) == 1
    assert (e3 - e2) == 1


# ---------------------------------------------------------------------------
# Last-Event-ID resume (replay)
# ---------------------------------------------------------------------------

async def test_subscribe_with_after_id_replays_buffered_events(bus) -> None:
    """A reconnecting client passing after_id=N receives all events with id > N."""
    e1 = bus.publish("r", "scan_started", {})
    e2 = bus.publish("r", "scanner_started", {"scanner": "a"})
    e3 = bus.publish("r", "scanner_completed", {"scanner": "a"})

    # Reconnect from after e1.
    q = await bus.subscribe("r", after_id=e1)
    events = []
    while not q.empty():
        events.append(await asyncio.wait_for(q.get(), timeout=0.5))
    eids = [e[0] for e in events]
    assert eids == [e2, e3]


async def test_subscribe_with_after_id_zero_replays_all(bus) -> None:
    """after_id=0 means 'give me everything buffered'."""
    bus.publish("r", "scan_started", {})
    bus.publish("r", "scanner_started", {})
    q = await bus.subscribe("r", after_id=0)
    assert q.qsize() == 2


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

async def test_buffer_trims_to_capacity(bus) -> None:
    """Buffer is bounded — events past capacity get dropped (oldest first)."""
    # Capacity is the module-level default of 1000.
    for _ in range(100):
        bus.publish("r", "noop", {})
    # The soft cap is 1000; we published 100 so all fit.
    buffer = bus._buffers["r"]
    assert len(buffer.events) == 100

    # Push past capacity and check the bound holds.
    for _ in range(2000):
        bus.publish("r", "noop", {})
    assert len(buffer.events) <= 1000
    # Oldest events should be gone.
    assert buffer.events[0][0] > 100


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

async def test_publishes_isolated_per_run(bus) -> None:
    """Events from run-A don't leak into run-B's subscribers."""
    qa = await bus.subscribe("run-A")
    qb = await bus.subscribe("run-B")
    bus.publish("run-A", "scan_started", {"who": "A"})
    bus.publish("run-B", "scan_started", {"who": "B"})

    a_event = await asyncio.wait_for(qa.get(), timeout=0.5)
    b_event = await asyncio.wait_for(qb.get(), timeout=0.5)
    assert a_event[2] == {"who": "A"}
    assert b_event[2] == {"who": "B"}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

async def test_unsubscribe_removes_queue(bus) -> None:
    """After unsubscribe, the queue is no longer in the subscribers list."""
    q = await bus.subscribe("r")
    assert q in bus._buffers["r"].subscribers
    bus.unsubscribe("r", q)
    assert q not in bus._buffers["r"].subscribers


async def test_drop_clears_buffer_for_run(bus) -> None:
    """drop(run_id) clears the buffer and any future subscribe starts fresh."""
    bus.publish("r", "scan_started", {})
    assert bus._buffers["r"].events  # non-empty
    bus.drop("r")
    # After drop, a fresh subscribe sees nothing.
    q = await bus.subscribe("r")
    assert q.empty()


async def test_drop_does_not_affect_other_runs(bus) -> None:
    bus.publish("a", "scan_started", {})
    bus.publish("b", "scan_started", {})
    bus.drop("a")
    assert bus._buffers["b"].events  # b still has its event
