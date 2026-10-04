"""Runs: starting them, listing them, and watching them happen."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

from sot.api import deps
from sot.config import settings
from sot.ingest.service import ingest_paths

router = APIRouter(tags=["runs"])

#: How long to wait for a run to announce itself before giving up on live streaming.
START_TIMEOUT_SECONDS = 20

#: Strong references to running tasks. Without these the event loop may collect a
#: task mid-run, which looks exactly like a run that silently stopped.
_BACKGROUND: set[asyncio.Task] = set()


def _parse_overrides(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        # Also accept the CLI's form, so the same string works in both places.
        return dict(item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {str(key): str(value) for key, value in parsed.items()}


def _run_in_background(
    paths: list[str],
    pack: str | None,
    as_of: date | None,
    overrides: dict[str, str],
    started: asyncio.Event,
    holder: dict[str, Any],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Execute one ingest, announcing the run id as soon as it exists."""

    def announce(context: Any) -> None:
        holder["run_id"] = context.run_id
        deps.register(
            context.run_id,
            context.events,
            sources=tuple(paths),
            pack=context.pack.id,
            as_of=context.as_of.isoformat(),
        )
        loop.call_soon_threadsafe(started.set)

    with deps.RUN_LOCK:
        try:
            result = ingest_paths(
                paths,
                pack_id=pack,
                as_of=as_of,
                db=deps.db(),
                type_overrides=overrides,
                on_start=announce,
            )
            holder["result"] = result
        except Exception as exc:  # pragma: no cover - the run context catches its own
            holder["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if holder.get("run_id"):
                deps.finish(holder["run_id"])
            loop.call_soon_threadsafe(started.set)


@router.post("/ingest")
async def ingest(
    files: list[UploadFile] = File(...),
    as_of: str | None = Form(default=None),
    pack: str | None = Form(default=None),
    type_overrides: str | None = Form(default=None),
) -> dict[str, Any]:
    """Accept an upload and start a run.

    Returns as soon as the run has an identifier, not when it finishes, so the canvas
    can subscribe and watch it happen rather than waiting on a blank screen.
    """
    token = uuid.uuid4().hex[:12]
    target = deps.upload_dir(token)
    saved: list[str] = []
    for upload in files:
        name = (upload.filename or "upload").replace("/", "_")
        destination = target / name
        with open(destination, "wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        saved.append(str(destination))

    if not saved:
        raise HTTPException(status_code=400, detail="no files were uploaded")

    parsed_as_of = None
    if as_of:
        try:
            parsed_as_of = date.fromisoformat(as_of)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"as_of must be YYYY-MM-DD, got {as_of!r}"
            ) from None

    started = asyncio.Event()
    holder: dict[str, Any] = {}
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(
        asyncio.to_thread(
            _run_in_background,
            saved,
            pack,
            parsed_as_of,
            _parse_overrides(type_overrides),
            started,
            holder,
            loop,
        )
    )
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    try:
        await asyncio.wait_for(started.wait(), timeout=START_TIMEOUT_SECONDS)
    except TimeoutError:
        task.cancel()
        raise HTTPException(status_code=504, detail="the run did not start in time") from None

    if holder.get("error") and not holder.get("run_id"):
        raise HTTPException(status_code=500, detail=holder["error"])
    return {"run_id": holder.get("run_id"), "files": len(saved), "token": token}


@router.get("/runs")
def list_runs(limit: int = 20) -> dict[str, Any]:
    """Recent runs, newest first."""
    rows = deps.db().query(
        "SELECT run_id, started_at, finished_at, status, pack, as_of, duration_ms, "
        "engine_version FROM runs ORDER BY started_at DESC LIMIT ?",
        [limit],
    )
    return {"runs": [_run_row(row) for row in rows]}


def _run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "status": row["status"],
        "pack": row["pack"],
        "as_of": row["as_of"].isoformat() if row["as_of"] else None,
        "duration_ms": row["duration_ms"],
        "engine_version": row.get("engine_version"),
    }


@router.get("/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    """One run, with its per-step numbers and its flag counts."""
    database = deps.db()
    resolved = run_id if run_id != "latest" else deps.latest_run_id(database)
    if not resolved:
        raise HTTPException(status_code=404, detail="no runs yet")
    row = database.query_one("SELECT * FROM runs WHERE run_id = ?", [resolved])
    if row is None:
        raise HTTPException(status_code=404, detail=f"no run {resolved}")

    nodes = database.query(
        "SELECT * FROM node_stats WHERE run_id = ? ORDER BY started_at, node_id", [resolved]
    )
    counts = database.query(
        "SELECT severity, count(*) AS n FROM flags WHERE run_id = ? GROUP BY severity",
        [resolved],
    )
    files = database.query(
        "SELECT f.original_name, f.detected_source, f.detect_confidence, f.media_kind, "
        "f.size_bytes, rf.is_duplicate FROM run_files rf JOIN files f USING (file_id) "
        "WHERE rf.run_id = ? ORDER BY f.original_name",
        [resolved],
    )
    return {
        **_run_row(row),
        "flags": {item["severity"]: item["n"] for item in counts},
        "nodes": [
            {
                "node_id": node["node_id"],
                "type": node["node_type"],
                "label": node["label"],
                "status": node["status"],
                "rows_in": node["rows_in"],
                "rows_out": node["rows_out"],
                "quarantined": node["quarantined"],
                "duration_ms": node["duration_ms"],
                "flags": {
                    "BLOCKER": node["flags_blocker"],
                    "CRITICAL": node["flags_critical"],
                    "WARNING": node["flags_warning"],
                    "INFO": node["flags_info"],
                },
                "error": node["error"],
            }
            for node in nodes
        ],
        "files": files,
        "records": database.scalar("SELECT count(*) FROM std_records WHERE run_id = ?", [resolved]),
        "segments": database.scalar(
            "SELECT count(*) FROM shift_segments WHERE run_id = ?", [resolved]
        ),
    }


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, replay: bool = False) -> EventSourceResponse:
    """Stream a run's events.

    A run still in flight streams live. A finished one replays from the stored log,
    which is the demo-day fallback: the canvas lights up exactly as it did, with no
    recomputation and nothing that can fail twice.
    """
    database = deps.db()
    resolved = run_id if run_id != "latest" else deps.latest_run_id(database)
    if not resolved:
        raise HTTPException(status_code=404, detail="no runs yet")

    live = deps.active(resolved)
    if live is not None and not live.finished and not replay:
        return EventSourceResponse(_stream_live(live))
    return EventSourceResponse(_stream_stored(database, resolved))


async def _stream_live(run: deps.ActiveRun):
    """Follow a run as it happens, catching up on whatever already occurred."""
    seen = 0
    while True:
        events = run.log.events
        for event in events[seen:]:
            yield {"event": str(event.type), "data": json.dumps(event.as_sse())}
        seen = len(events)
        if run.finished and seen >= len(run.log.events):
            return
        await asyncio.sleep(0.05)


async def _stream_stored(database: Any, run_id: str, delay: float = 0.04):
    """Replay a stored run, paced so the canvas animates rather than snapping."""
    rows = database.query(
        "SELECT seq, ts, event_type, node_id, payload_json FROM run_events "
        "WHERE run_id = ? ORDER BY seq",
        [run_id],
    )
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        yield {
            "event": row["event_type"],
            "data": json.dumps(
                {
                    "seq": row["seq"],
                    "ts": row["ts"].isoformat() if row["ts"] else None,
                    "type": row["event_type"],
                    "node_id": row["node_id"],
                    **payload,
                }
            ),
        }
        await asyncio.sleep(delay)


@router.post("/runs/{run_id}/rerun")
async def rerun(run_id: str) -> dict[str, Any]:
    """Run the same files again, with whatever decisions are now in force.

    This is the other half of the decision loop: resolve a finding, run it again, and
    watch it disappear.
    """
    database = deps.db()
    resolved = run_id if run_id != "latest" else deps.latest_run_id(database)
    previous = deps.active(resolved) if resolved else None
    sources: list[str] = list(previous.sources) if previous else []

    if not sources and resolved:
        rows = database.query(
            "SELECT f.stored_path FROM run_files rf JOIN files f USING (file_id) "
            "WHERE rf.run_id = ? ORDER BY f.original_name",
            [resolved],
        )
        sources = [row["stored_path"] for row in rows]
    if not sources:
        raise HTTPException(status_code=404, detail=f"nothing to re-run for {run_id}")

    row = database.query_one("SELECT pack, as_of FROM runs WHERE run_id = ?", [resolved])
    pack = row["pack"] if row else settings().default_pack
    as_of = row["as_of"] if row else None

    started = asyncio.Event()
    holder: dict[str, Any] = {}
    loop = asyncio.get_running_loop()
    # Held in _BACKGROUND so the task is not garbage collected mid-run.
    task = asyncio.create_task(
        asyncio.to_thread(_run_in_background, sources, pack, as_of, {}, started, holder, loop)
    )
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    await asyncio.wait_for(started.wait(), timeout=START_TIMEOUT_SECONDS)
    return {"run_id": holder.get("run_id"), "reran": resolved}


@router.post("/runs/{run_id}/replay")
def replay(run_id: str) -> dict[str, Any]:
    """Point the client at the stored event stream. Nothing is recomputed."""
    database = deps.db()
    resolved = run_id if run_id != "latest" else deps.latest_run_id(database)
    count = database.scalar("SELECT count(*) FROM run_events WHERE run_id = ?", [resolved])
    if not count:
        raise HTTPException(status_code=404, detail=f"no stored events for {run_id}")
    return {
        "run_id": resolved,
        "events": count,
        "stream": f"/api/runs/{resolved}/events?replay=true",
    }
