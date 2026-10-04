"""Human decisions: the memory of the system.

Writing one is how a person corrects the engine, and reading them back at the start
of every run is how the correction sticks. Keyed on a fingerprint of the record's
content rather than its position, so a re-export does not undo somebody's work.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sot.api import deps
from sot.canon import canonical_json
from sot.decisions.store import (
    ACCEPT_MATCH,
    CODE_MAP,
    DISMISS_FLAG,
    HEADER_MAP,
    NOTE,
    REJECT_MATCH,
    load_decisions,
)
from sot.ids import stable_id

router = APIRouter(tags=["decisions"])

KNOWN_TYPES = {ACCEPT_MATCH, REJECT_MATCH, CODE_MAP, HEADER_MAP, DISMISS_FLAG, NOTE}


class DecisionIn(BaseModel):
    """One decision, as the UI sends it."""

    decision_type: str
    key: dict[str, Any] = Field(default_factory=dict)
    value: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    actor: str = "ui"


@router.get("/decisions")
def list_decisions() -> dict[str, Any]:
    """Every decision in force, newest first, with the audit trail."""
    database = deps.db()
    rows = database.query("SELECT * FROM decisions ORDER BY created_at DESC, decision_id DESC")
    decisions = load_decisions(database)
    return {
        "digest": decisions.digest,
        "count": len(decisions),
        "decisions": [
            {
                "decision_id": row["decision_id"],
                "type": row["decision_type"],
                "key": row["key_json"],
                "value": row["value_json"],
                "actor": row["actor"],
                "reason": row["reason"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "active": bool(row["active"]),
            }
            for row in rows
        ],
    }


@router.post("/decisions")
def create_decision(decision: DecisionIn) -> dict[str, Any]:
    """Record a decision. It applies from the next run onwards."""
    if decision.decision_type not in KNOWN_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown decision type {decision.decision_type!r}; expected one of "
            f"{sorted(KNOWN_TYPES)}",
        )
    if not decision.key:
        raise HTTPException(status_code=400, detail="a decision needs a key")

    database = deps.db()
    decision_id = stable_id(
        "DC", {"type": decision.decision_type, "key": decision.key, "value": decision.value}
    )
    database.execute("DELETE FROM decisions WHERE decision_id = ?", [decision_id])
    database.insert_rows(
        "decisions",
        [
            {
                "decision_id": decision_id,
                "decision_type": decision.decision_type,
                "key_json": canonical_json(decision.key),
                "value_json": canonical_json(decision.value),
                "actor": decision.actor,
                "reason": decision.reason,
                "created_at": datetime.now(),
                "active": True,
            }
        ],
    )
    return {
        "decision_id": decision_id,
        "applies_from": "the next run",
        "digest": load_decisions(database).digest,
    }


@router.delete("/decisions/{decision_id}")
def retract_decision(decision_id: str) -> dict[str, Any]:
    """Withdraw a decision. Kept in the log, marked inactive."""
    database = deps.db()
    existing = database.query_one(
        "SELECT decision_id FROM decisions WHERE decision_id = ?", [decision_id]
    )
    if existing is None:
        raise HTTPException(status_code=404, detail=f"no decision {decision_id}")
    database.execute("UPDATE decisions SET active = FALSE WHERE decision_id = ?", [decision_id])
    return {"decision_id": decision_id, "active": False}
