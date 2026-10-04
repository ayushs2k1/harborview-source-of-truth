"""The run context: what every pipeline step writes through.

A run owns the identifiers, the as-of date, the pack, the flag collector, and the
event log, and it wraps each step so that a step which fails does not take the run
with it. That last part is principle 1 made concrete - a step that raises becomes a
BLOCKER flag naming the step, downstream steps run with whatever data exists and are
marked degraded, and the user gets a report rather than a stack trace.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sot.canon import canonical_json
from sot.config import ENGINE_VERSION
from sot.ids import digest
from sot.ids import run_id as make_run_id
from sot.ingest.contracts import Pack
from sot.pipeline.events import EventLog, EventType
from sot.rules.builder import FlagCollector
from sot.rules.model import Severity
from sot.store.db import Database

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

RUN_OK = "OK"
RUN_DEGRADED = "DEGRADED"
RUN_FAILED = "FAILED"
RUN_RUNNING = "RUNNING"


@dataclass
class NodeResult:
    """What one step did."""

    node_id: str
    label: str
    node_type: str
    status: str = STATUS_OK
    rows_in: int = 0
    rows_out: int = 0
    quarantined: int = 0
    duration_ms: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    #: Inputs this step expected and did not get, so downstream can tell why.
    missing_inputs: list[str] = field(default_factory=list)

    def as_row(self, run_id: str, flag_counts: dict[str, int]) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
            "status": self.status,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "quarantined": self.quarantined,
            "flags_blocker": flag_counts.get("BLOCKER", 0),
            "flags_critical": flag_counts.get("CRITICAL", 0),
            "flags_warning": flag_counts.get("WARNING", 0),
            "flags_info": flag_counts.get("INFO", 0),
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class RunContext:
    """One execution of the pipeline."""

    def __init__(
        self,
        pack: Pack,
        as_of: date,
        db: Database,
        *,
        input_digest: str = "",
        started_at: datetime | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.pack = pack
        self.as_of = as_of
        self.db = db
        self.started_at = started_at or datetime.now()
        self.input_digest = input_digest or digest({"pack": pack.id, "as_of": as_of})
        self.run_id = make_run_id(self.input_digest, self.started_at.isoformat())
        self.flags = FlagCollector()
        self.events = EventLog()
        self.nodes: list[NodeResult] = []
        self.params = params or {}
        self.status = RUN_RUNNING
        self._degraded = False

    # -- steps -------------------------------------------------------------

    @contextmanager
    def node(self, node_id: str, label: str, node_type: str) -> Iterator[NodeResult]:
        """Run one step, recording what it did and surviving what it raises."""
        result = NodeResult(node_id=node_id, label=label, node_type=node_type)
        result.started_at = datetime.now()
        started = time.perf_counter()
        self.events.append(EventType.NODE_STARTED, node_id, label=label, node_type=node_type)
        before = len(self.flags.flags)
        try:
            yield result
        except Exception as exc:
            result.status = STATUS_FAILED
            result.error = f"{type(exc).__name__}: {exc}"
            self._degraded = True
            self.flags.raise_flag(
                "NODE_FAILED",
                {"label": label, "node_id": node_id, "error": result.error},
                key_parts=(node_id,),
                node_id=node_id,
            )
            # The traceback goes to the event log, not to the user's screen.
            self.events.append(
                EventType.NODE_PROGRESS, node_id, traceback=traceback.format_exc()[-4000:]
            )
        finally:
            result.finished_at = datetime.now()
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            if result.status == STATUS_DEGRADED:
                self._degraded = True
            self.nodes.append(result)
            counts = self._flag_counts(self.flags.flags[before:])
            self.events.append(
                EventType.NODE_FINISHED,
                node_id,
                status=result.status,
                rows_in=result.rows_in,
                rows_out=result.rows_out,
                quarantined=result.quarantined,
                duration_ms=result.duration_ms,
                flags=counts,
            )

    def progress(self, node_id: str, **payload: Any) -> None:
        """Report partial progress from inside a long step."""
        self.events.append(EventType.NODE_PROGRESS, node_id, **payload)

    @staticmethod
    def _flag_counts(flags: list[Any]) -> dict[str, int]:
        counts = {str(severity): 0 for severity in Severity}
        for flag in flags:
            counts[str(flag.severity)] += 1
        return counts

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Record the run and announce it.

        The identifier is resolved to the millisecond, but two runs really can start
        inside the same one, so a taken id gets a suffix rather than an exception.
        """
        if self.db.scalar("SELECT count(*) FROM runs WHERE run_id = ?", [self.run_id]):
            suffix = 2
            while self.db.scalar(
                "SELECT count(*) FROM runs WHERE run_id = ?", [f"{self.run_id}.{suffix}"]
            ):
                suffix += 1
            self.run_id = f"{self.run_id}.{suffix}"

        self.db.insert_rows(
            "runs",
            [
                {
                    "run_id": self.run_id,
                    "started_at": self.started_at,
                    "status": RUN_RUNNING,
                    "pack": self.pack.id,
                    "pack_version": str(self.pack.settings.get("version", "")),
                    "as_of": self.as_of,
                    "input_digest": self.input_digest,
                    "params_json": canonical_json(self.params),
                    "engine_version": ENGINE_VERSION,
                }
            ],
        )
        self.events.append(
            EventType.RUN_STARTED,
            run_id=self.run_id,
            pack=self.pack.id,
            as_of=self.as_of.isoformat(),
        )

    def finish(self) -> str:
        """Persist flags, node stats, and events, and close the run."""
        flags = self.flags.finalize()
        worst = self.flags.worst_severity()
        if any(node.status == STATUS_FAILED for node in self.nodes) or self._degraded:
            self.status = RUN_DEGRADED
        else:
            self.status = RUN_OK

        self.db.insert_rows("flags", [flag.as_row(self.run_id) for flag in flags])
        self.db.insert_rows(
            "flag_evidence",
            [
                item.as_row(self.run_id, flag.flag_id, seq)
                for flag in flags
                for seq, item in enumerate(flag.evidence)
            ],
        )

        per_node: dict[str, dict[str, int]] = {}
        for flag in flags:
            counts = per_node.setdefault(flag.node_id or "", {str(s): 0 for s in Severity})
            counts[str(flag.severity)] += 1
        self.db.insert_rows(
            "node_stats",
            [node.as_row(self.run_id, per_node.get(node.node_id, {})) for node in self.nodes],
        )

        finished = datetime.now()
        self.events.append(
            EventType.RUN_FINISHED,
            status=self.status,
            flags=self.flags.counts_by_severity(),
            worst_severity=str(worst) if worst else None,
            duration_ms=int((finished - self.started_at).total_seconds() * 1000),
        )
        self.db.insert_rows("run_events", self.events.rows(self.run_id))
        self.db.execute(
            "UPDATE runs SET status = ?, finished_at = ?, duration_ms = ? WHERE run_id = ?",
            [
                self.status,
                finished,
                int((finished - self.started_at).total_seconds() * 1000),
                self.run_id,
            ],
        )
        return self.status
