"""The flag inbox."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from sot.api import deps
from sot.rules.catalog import RULES

router = APIRouter(tags=["flags"])

SEVERITY_ORDER = {"BLOCKER": 0, "CRITICAL": 1, "WARNING": 2, "INFO": 3}


def _flag_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "flag_id": row["flag_id"],
        "run_id": row["run_id"],
        "rule_code": row["rule_code"],
        "severity": row["severity"],
        "category": row["category"],
        "title": row["title"],
        "message": row["message"],
        "entities": json.loads(row["entities_json"] or "[]"),
        "suggested_action": row["suggested_action"],
        "owner_role": row["owner_role"],
        "status": row["status"],
        "occurrence_count": row["occurrence_count"],
        "node_id": row["node_id"],
        "params": json.loads(row["params_json"] or "{}"),
    }


@router.get("/flags")
def list_flags(
    run_id: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    status: str | None = None,
    rule_code: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=500, le=5000),
) -> dict[str, Any]:
    """Findings for a run, worst first, with the filters the inbox offers."""
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    if not resolved:
        return {"run_id": None, "flags": [], "counts": {}, "total": 0}

    clauses = ["run_id = ?"]
    params: list[Any] = [resolved]
    for column, value in (
        ("severity", severity),
        ("category", category),
        ("status", status),
        ("rule_code", rule_code),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if entity_id:
        clauses.append("entities_json LIKE ?")
        params.append(f"%{entity_id}%")

    where = " AND ".join(clauses)
    rows = database.query(f"SELECT * FROM flags WHERE {where}", params)
    flags = sorted(
        (_flag_row(row) for row in rows),
        key=lambda item: (
            SEVERITY_ORDER.get(item["severity"], 9),
            item["rule_code"],
            item["flag_id"],
        ),
    )
    counts = database.query(
        "SELECT severity, count(*) AS n FROM flags WHERE run_id = ? GROUP BY severity", [resolved]
    )
    return {
        "run_id": resolved,
        "flags": flags[:limit],
        "total": len(flags),
        "counts": {item["severity"]: item["n"] for item in counts},
    }


@router.get("/flags/{flag_id}")
def flag_detail(flag_id: str, run_id: str | None = None) -> dict[str, Any]:
    """One finding with the evidence behind it, and what the rule means."""
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    row = database.query_one(
        "SELECT * FROM flags WHERE flag_id = ? AND run_id = ?", [flag_id, resolved]
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"no flag {flag_id}")

    evidence = database.query(
        "SELECT e.*, f.original_name, f.media_kind FROM flag_evidence e "
        "LEFT JOIN files f USING (file_id) WHERE e.run_id = ? AND e.flag_id = ? ORDER BY e.seq",
        [resolved, flag_id],
    )
    spec = RULES.get(row["rule_code"]) if RULES.has(row["rule_code"]) else None
    return {
        **_flag_row(row),
        "evidence": [
            {
                "file_id": item["file_id"],
                "file": item["original_name"],
                "media_kind": item["media_kind"],
                "source_type": item["source_type"],
                "row": item["row_index"],
                "page": item["page"],
                "column": item["column_name"],
                "raw_value": item["raw_value"],
                "bbox": (
                    [item["x0"], item["top"], item["x1"], item["bottom"]]
                    if item["x0"] is not None
                    else None
                ),
            }
            for item in evidence
        ],
        "rule": {
            "meaning": spec.meaning if spec else "",
            "priority": spec.priority if spec else "",
            "severity_note": spec.severity_note if spec else "",
            "configured_by": list(spec.params_from_pack) if spec else [],
        },
    }


@router.get("/rules")
def list_rules() -> dict[str, Any]:
    """The catalog, for the UI to explain a code without a round trip."""
    live = RULES.implemented_codes()
    return {
        "rules": [
            {
                "code": spec.code,
                "severity": str(spec.severity),
                "category": str(spec.category),
                "priority": spec.priority,
                "meaning": spec.meaning,
                "title": spec.title,
                "owner_role": str(spec.owner_role),
                "implemented": spec.code in live,
                "severity_note": spec.severity_note,
            }
            for spec in RULES.all()
        ]
    }
