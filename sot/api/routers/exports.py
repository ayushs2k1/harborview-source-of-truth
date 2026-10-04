"""CSV exports. Everything the UI shows should also be obtainable as a file."""

from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from sot.api import deps

router = APIRouter(prefix="/exports", tags=["exports"])

#: What each export name selects. Written out rather than taking a table name from
#: the URL, which would be an open invitation to read anything in the database.
EXPORTS: dict[str, tuple[str, str]] = {
    "flags": (
        "SELECT severity, category, rule_code, title, message, suggested_action, "
        "owner_role, occurrence_count, status FROM flags WHERE run_id = ? "
        "ORDER BY severity, rule_code",
        "flags",
    ),
    "pbj_daily_hours": (
        "SELECT facility_code AS facility, work_date, display_name, role_code AS role, "
        "pbj_job_code, scheduled_hours, meal_deduction, pbj_hours, tier FROM daily_hours "
        "WHERE run_id = ? ORDER BY facility_code, work_date, display_name",
        "pbj_daily_hours",
    ),
    "person_weeks": (
        "SELECT person_id, period_start, period_end, facility_code, role_code, "
        "scheduled_work_hours, scheduled_pto_hours, paid_hours, delta, status, direction, "
        "explained_by_pto, employed, permitted FROM match_person_week WHERE run_id = ? "
        "ORDER BY person_id, period_start",
        "person_weeks",
    ),
    "person_days": (
        "SELECT person_id, work_date, facility_code, role_code, work_hours, pto_hours, "
        "credential_valid, employed, has_overlap FROM match_person_day WHERE run_id = ? "
        "ORDER BY person_id, work_date",
        "person_days",
    ),
    "credentials": (
        "SELECT holder_id, credential_type, number_norm, expires_on, last_verified, "
        "status, state FROM credentials WHERE run_id = ? ORDER BY expires_on",
        "credentials",
    ),
    "claims": (
        "SELECT entity_type, entity_id, attribute, value_norm, value_raw, source_type, "
        "observed_on, quality FROM claims WHERE run_id = ? ORDER BY entity_id, attribute",
        "claims",
    ),
    "golden": (
        "SELECT entity_type, entity_id, attribute, value_norm, source_type, rule, "
        "candidate_count, conflict_count FROM golden_attributes WHERE run_id = ? "
        "ORDER BY entity_id, attribute",
        "golden_attributes",
    ),
    "quarantine": (
        "SELECT file_id, row_index, rule_code, field_count, expected_count, raw_text "
        "FROM quarantine WHERE run_id = ? ORDER BY file_id, row_index",
        "quarantine",
    ),
}


@router.get("/{name}.csv")
def export(name: str, run_id: str | None = None) -> StreamingResponse:
    """One export as CSV."""
    if name not in EXPORTS:
        raise HTTPException(
            status_code=404,
            detail=f"no export {name!r}; available: {sorted(EXPORTS)}",
        )
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="no runs yet")

    sql, _ = EXPORTS[name]
    rows = database.query(sql, [resolved])
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if rows:
        writer.writerow(list(rows[0]))
        for row in rows:
            writer.writerow([_cell(value) for value in row.values()])
    else:
        writer.writerow(["(no rows)"])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}_{resolved}.csv"'},
    )


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


@router.get("")
def list_exports() -> dict[str, Any]:
    return {"exports": sorted(EXPORTS)}
