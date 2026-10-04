"""Shared state for the API.

Two things live here: the runs currently in flight, so a browser can subscribe to a
run it has only just started, and a lock that keeps runs serialized. One writer to
DuckDB at a time removes a class of interleaving bugs that would otherwise surface as
output that changes between identical runs.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sot.config import settings
from sot.pipeline.events import EventLog
from sot.store.db import Database, get_db

#: Runs may not overlap: one writer, and a deterministic order.
RUN_LOCK = threading.Lock()

_ACTIVE: dict[str, ActiveRun] = {}
_ACTIVE_LOCK = threading.Lock()

#: Finished runs keep their log briefly so a browser that connects late still sees it.
MAX_REMEMBERED = 8


@dataclass
class ActiveRun:
    """A run the API can report on while it is still happening."""

    run_id: str
    log: EventLog
    started_at: datetime = field(default_factory=datetime.now)
    finished: bool = False
    #: The files it was given, so it can be run again.
    sources: tuple[str, ...] = ()
    pack: str = ""
    as_of: str = ""


def register(run_id: str, log: EventLog, **details: Any) -> ActiveRun:
    """Record a run so its events can be streamed."""
    with _ACTIVE_LOCK:
        active = ActiveRun(run_id=run_id, log=log, **details)
        _ACTIVE[run_id] = active
        while len(_ACTIVE) > MAX_REMEMBERED:
            oldest = min(_ACTIVE.values(), key=lambda item: item.started_at)
            _ACTIVE.pop(oldest.run_id, None)
        return active


def finish(run_id: str) -> None:
    with _ACTIVE_LOCK:
        if run_id in _ACTIVE:
            _ACTIVE[run_id].finished = True


def active(run_id: str) -> ActiveRun | None:
    with _ACTIVE_LOCK:
        return _ACTIVE.get(run_id)


def latest() -> ActiveRun | None:
    with _ACTIVE_LOCK:
        if not _ACTIVE:
            return None
        return max(_ACTIVE.values(), key=lambda item: item.started_at)


def db() -> Database:
    return get_db()


def upload_dir(run_token: str) -> Path:
    """Where an upload is staged before it is landed by content hash."""
    target = settings().var_dir / "uploads" / run_token
    target.mkdir(parents=True, exist_ok=True)
    return target


def latest_run_id(database: Database) -> str | None:
    """The most recent run, which is what the UI shows by default."""
    row = database.query_one("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1")
    return row["run_id"] if row else None


def resolve_run_id(database: Database, run_id: str | None) -> str | None:
    return run_id or latest_run_id(database)


def iter_sse(payloads: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Adapt plain dictionaries to what the SSE helper expects."""
    for payload in payloads:
        yield {"data": payload}
