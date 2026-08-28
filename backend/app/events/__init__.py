"""In-memory per-run event bus.

Worker publishes scanner-status / finding-count / run-completion events
as a scan progresses. The SSE endpoint subscribes and streams them to
clients. Events are buffered per run (default 1000) for Last-Event-ID
resume.

This is intentionally in-memory and per-process — single-user, single
server. A multi-process deployment would need a real broker.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


log = logging.getLogger(__name__)


@dataclass
class _RunBuffer:
    """Per-run ring buffer + subscriber queue."""

    events: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    """List of (event_id, event_kind, payload) tuples in order."""
    next_id: int = 1
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    capacity: int = 1000

    def publish(self, kind: str, payload: dict[str, Any]) -> int:
        """Append an event, notify subscribers, return the event id."""
        eid = self.next_id
        self.next_id += 1
        self.events.append((eid, kind, payload))
        if len(self.events) > self.capacity:
            # Drop oldest — capacity is a soft bound.
            self.events = self.events[-self.capacity:]
        for q in self.subscribers:
            try:
                q.put_nowait((eid, kind, payload))
            except asyncio.QueueFull:
                log.warning("subscriber queue full; event dropped")
        return eid

    def events_since(self, after_id: int) -> list[tuple[int, str, dict[str, Any]]]:
        return [(eid, k, p) for eid, k, p in self.events if eid > after_id]

    async def subscribe(self, after_id: int = 0) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        # Replay buffered events first.
        for eid, kind, payload in self.events_since(after_id):
            await q.put((eid, kind, payload))
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)


class EventBus:
    """Process-wide event bus. Tracks per-run buffers."""

    def __init__(self) -> None:
        self._buffers: dict[str, _RunBuffer] = defaultdict(_RunBuffer)
        self._lock = asyncio.Lock()

    def publish(self, run_id: str, kind: str, payload: dict[str, Any]) -> int:
        return self._buffers[run_id].publish(kind, payload)

    async def subscribe(self, run_id: str, after_id: int = 0) -> asyncio.Queue:
        return await self._buffers[run_id].subscribe(after_id)

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        self._buffers[run_id].unsubscribe(q)

    def drop(self, run_id: str) -> None:
        self._buffers.pop(run_id, None)


# Process-wide singleton. The worker and the SSE endpoint share this.
bus = EventBus()


__all__ = ["bus", "EventBus"]
