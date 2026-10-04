"""Run events.

Every node reports what it did as it goes. The same stream serves three purposes: it
drives the live pipeline canvas over SSE, it is persisted so a finished run can be
replayed without recomputing anything (the demo-day fallback), and it is the run log
when something goes wrong.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sot.canon import canonical_json


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_PROGRESS = "node_progress"
    NODE_FINISHED = "node_finished"
    RUN_FINISHED = "run_finished"


@dataclass(frozen=True)
class Event:
    """One thing that happened, in order."""

    seq: int
    ts: datetime
    type: EventType
    node_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "seq": self.seq,
            "ts": self.ts,
            "event_type": str(self.type),
            "node_id": self.node_id,
            "payload_json": canonical_json(self.payload),
        }

    def as_sse(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts.isoformat(),
            "type": str(self.type),
            "node_id": self.node_id,
            **self.payload,
        }


class EventLog:
    """An ordered, append-only log with live subscribers.

    Sequence numbers come from the log rather than a clock, so two events in the same
    millisecond still have a defined order - which matters, because the canvas replays
    them in sequence.
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._events: list[Event] = []
        self._subscribers: list[Callable[[Event], None]] = []
        self._lock = threading.RLock()
        self._clock = clock or datetime.now

    def append(self, event_type: EventType, node_id: str | None = None, **payload: Any) -> Event:
        """Record an event and hand it to every subscriber."""
        with self._lock:
            event = Event(len(self._events), self._clock(), event_type, node_id, payload)
            self._events.append(event)
            subscribers = list(self._subscribers)
        for notify in subscribers:
            try:
                notify(event)
            except Exception:
                # A broken listener - a disconnected browser, usually - must not take
                # the run down with it.
                continue
        return event

    def subscribe(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        """Register a listener. Returns a function that removes it again."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    @property
    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [event for event in self.events if event.type is event_type]

    def rows(self, run_id: str) -> list[dict[str, Any]]:
        return [event.as_row(run_id) for event in self.events]
