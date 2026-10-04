"""People, and the evidence behind each of them."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from sot.api import deps

router = APIRouter(tags=["people"])


@router.get("/persons")
def list_persons(run_id: str | None = None) -> dict[str, Any]:
    """Everybody the run knows about, with how much attention they need."""
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    if not resolved:
        return {"run_id": None, "persons": []}

    people = database.query(
        "SELECT * FROM persons WHERE run_id = ? ORDER BY display_name", [resolved]
    )
    flag_counts: dict[str, dict[str, int]] = {}
    for row in database.query(
        "SELECT entities_json, severity FROM flags WHERE run_id = ?", [resolved]
    ):
        for entity in json.loads(row["entities_json"] or "[]"):
            if entity.get("type") == "person":
                bucket = flag_counts.setdefault(entity["id"], {})
                bucket[row["severity"]] = bucket.get(row["severity"], 0) + 1

    credentials = database.query(
        "SELECT holder_id, credential_type, expires_on FROM credentials WHERE run_id = ?",
        [resolved],
    )
    by_holder: dict[str, list[dict[str, Any]]] = {}
    for item in credentials:
        by_holder.setdefault(item["holder_id"], []).append(
            {
                "type": item["credential_type"],
                "expires_on": item["expires_on"].isoformat() if item["expires_on"] else None,
            }
        )

    return {
        "run_id": resolved,
        "persons": [
            {
                "person_id": person["person_id"],
                "display_name": person["display_name"],
                "status": person["status"],
                "employee_id": person["employee_id"],
                "role": person["primary_role"],
                "home_facility": person["home_facility"],
                "credentials": by_holder.get(person["person_id"], []),
                "flags": flag_counts.get(person["person_id"], {}),
            }
            for person in people
        ],
    }


@router.get("/persons/{person_id}")
def person_detail(person_id: str, run_id: str | None = None) -> dict[str, Any]:
    """One person: every attribute, where it came from, and what lost."""
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    person = database.query_one(
        "SELECT * FROM persons WHERE run_id = ? AND person_id = ?", [resolved, person_id]
    )
    if person is None:
        raise HTTPException(status_code=404, detail=f"no person {person_id}")

    golden = database.query(
        "SELECT g.*, c.source_type AS claim_source, c.value_raw, c.locator_json, c.file_id "
        "FROM golden_attributes g LEFT JOIN claims c ON c.run_id = g.run_id "
        "AND c.claim_id = g.claim_id WHERE g.run_id = ? AND g.entity_type = 'person' "
        "AND g.entity_id = ? ORDER BY g.attribute",
        [resolved, person_id],
    )
    all_claims = database.query(
        "SELECT * FROM claims WHERE run_id = ? AND entity_type = 'person' AND entity_id = ? "
        "ORDER BY attribute, source_type",
        [resolved, person_id],
    )
    by_attribute: dict[str, list[dict[str, Any]]] = {}
    for claim in all_claims:
        by_attribute.setdefault(claim["attribute"], []).append(
            {
                "value": claim["value_norm"],
                "raw": claim["value_raw"],
                "source": claim["source_type"],
                "observed_on": claim["observed_on"].isoformat() if claim["observed_on"] else None,
                "file_id": claim["file_id"],
                "locator": json.loads(claim["locator_json"] or "{}"),
                "claim_id": claim["claim_id"],
            }
        )

    return {
        "run_id": resolved,
        "person": {
            "person_id": person["person_id"],
            "display_name": person["display_name"],
            "status": person["status"],
            "employee_id": person["employee_id"],
            "role": person["primary_role"],
            "home_facility": person["home_facility"],
        },
        "attributes": [
            {
                "attribute": item["attribute"],
                "value": item["value_norm"],
                "won_because": item["rule"],
                "source": item["claim_source"] or item["source_type"],
                "raw": item["value_raw"],
                "conflicts": item["conflict_count"],
                "all_claims": by_attribute.get(item["attribute"], []),
            }
            for item in golden
        ],
        "credentials": database.query(
            "SELECT * FROM credentials WHERE run_id = ? AND holder_id = ? ORDER BY expires_on",
            [resolved, person_id],
        ),
        "shifts": database.query(
            "SELECT work_date, facility_code, role_code, hours, category, start_ts, end_ts "
            "FROM shift_segments WHERE run_id = ? AND person_id = ? ORDER BY work_date",
            [resolved, person_id],
        ),
        "weeks": database.query(
            "SELECT * FROM match_person_week WHERE run_id = ? AND person_id = ? "
            "ORDER BY period_start, facility_code",
            [resolved, person_id],
        ),
    }


@router.get("/persons/{person_id}/graph")
def person_graph(person_id: str, run_id: str | None = None) -> dict[str, Any]:
    """The evidence graph: the person in the middle, every source record around them.

    Each edge carries the score that produced it and the features behind that score,
    which is what the waterfall renders. "Why did you decide these were the same
    nurse" is the question the whole system has to be able to answer.
    """
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    person = database.query_one(
        "SELECT * FROM persons WHERE run_id = ? AND person_id = ?", [resolved, person_id]
    )
    if person is None:
        raise HTTPException(status_code=404, detail=f"no person {person_id}")

    links = database.query(
        "SELECT * FROM links WHERE run_id = ? AND person_id = ? ORDER BY source_type, record_id",
        [resolved, person_id],
    )
    records = {
        row["record_id"]: row
        for row in database.query(
            "SELECT record_id, source_type, file_id, row_index, payload_json "
            "FROM std_records WHERE run_id = ? AND person_id = ?",
            [resolved, person_id],
        )
    }

    nodes: list[dict[str, Any]] = [
        {
            "id": person_id,
            "kind": "person",
            "label": person["display_name"],
            "status": person["status"],
        }
    ]
    edges: list[dict[str, Any]] = []
    for link in links:
        record = records.get(link["record_id"], {})
        nodes.append(
            {
                "id": link["record_id"],
                "kind": "record",
                "source": link["source_type"],
                "label": link["source_type"],
                "file_id": record.get("file_id"),
                "row": record.get("row_index"),
                "payload": json.loads(record.get("payload_json") or "{}"),
            }
        )
        edges.append(
            {
                "source": link["record_id"],
                "target": person_id,
                "score": link["score"],
                "band": link["band"],
                "decided_by": link["decided_by"],
                "explanation": json.loads(link["explanation_json"] or "{}"),
            }
        )

    for credential in database.query(
        "SELECT * FROM credentials WHERE run_id = ? AND holder_id = ?", [resolved, person_id]
    ):
        nodes.append(
            {
                "id": credential["credential_id"],
                "kind": "credential",
                "label": f"{credential['credential_type']} {credential['number_norm']}",
                "expires_on": (
                    credential["expires_on"].isoformat() if credential["expires_on"] else None
                ),
            }
        )
        edges.append(
            {
                "source": credential["credential_id"],
                "target": person_id,
                "band": "anchor",
                "decided_by": "anchor",
            }
        )

    return {"run_id": resolved, "nodes": nodes, "edges": edges}
