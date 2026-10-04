"""The three views the client's three problems map onto."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException

from sot.api import deps
from sot.ingest.contracts import load_pack
from sot.views.referral import assess_referral

router = APIRouter(prefix="/views", tags=["views"])


def _context(run_id: str | None) -> tuple[str, Any]:
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="no runs yet")
    row = database.query_one("SELECT pack, as_of FROM runs WHERE run_id = ?", [resolved])
    if row is None:
        raise HTTPException(status_code=404, detail=f"no run {resolved}")
    return (resolved, row)


@router.get("/staffing")
def staffing(
    run_id: str | None = None,
    facility: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Reportable hours by day, with the assumptions that produced them."""
    resolved, run = _context(run_id)
    database = deps.db()
    pack = load_pack(run["pack"])

    clauses = ["run_id = ?"]
    params: list[Any] = [resolved]
    if facility:
        clauses.append("facility_code = ?")
        params.append(facility)
    if date_from:
        clauses.append("work_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("work_date <= ?")
        params.append(date_to)

    rows = database.query(
        f"SELECT * FROM daily_hours WHERE {' AND '.join(clauses)} "
        "ORDER BY facility_code, work_date, display_name",
        params,
    )
    meal = pack.setting("pbj.meal_deduction", {}) or {}
    return {
        "run_id": resolved,
        "as_of": run["as_of"].isoformat() if run["as_of"] else None,
        "rows": [
            {
                "facility": row["facility_code"],
                "work_date": row["work_date"].isoformat(),
                "person_id": row["person_id"],
                "display_name": row["display_name"],
                "role": row["role_code"],
                "pbj_job_code": row["pbj_job_code"],
                "scheduled_hours": row["scheduled_hours"],
                "meal_deduction": row["meal_deduction"],
                "pbj_hours": row["pbj_hours"],
                "tier": row["tier"],
            }
            for row in rows
        ],
        "assumptions": {
            "meal_deduction_minutes": meal.get("minutes"),
            "meal_applies_from_hours": meal.get("min_shift_hours"),
            "split_at_midnight": pack.setting("pbj.split_at_midnight", True),
            "training_counted": pack.setting("pbj.include_training", False),
            "attribution": pack.setting("payroll_attribution", "shift_start"),
            "daily_cap_hours": pack.setting("pbj.daily_cap_hours"),
        },
        "summaries": _summaries(resolved, facility),
    }


def _summaries(run_id: str, facility: str | None) -> list[dict[str, Any]]:
    """Facility summaries, recomputed from the stored tables.

    Recomputed rather than stored: they are a few hundred rows of arithmetic, and a
    stored summary is one more thing that can disagree with the rows under it.
    """
    from sot.ingest.contracts import load_pack as _load
    from sot.views.staffing import DailyHours, StaffingResult, summarize

    database = deps.db()
    run = database.query_one("SELECT pack FROM runs WHERE run_id = ?", [run_id])
    pack = _load(run["pack"]) if run else None
    if pack is None:
        return []

    rows = [
        DailyHours(
            facility_code=row["facility_code"],
            work_date=row["work_date"],
            person_id=row["person_id"],
            display_name=row["display_name"] or "",
            role_code=row["role_code"],
            pbj_job_code=row["pbj_job_code"] or "",
            scheduled_hours=row["scheduled_hours"] or 0.0,
            meal_deduction=row["meal_deduction"] or 0.0,
            pbj_hours=row["pbj_hours"] or 0.0,
            tier=row["tier"],
        )
        for row in database.query("SELECT * FROM daily_hours WHERE run_id = ?", [run_id])
    ]
    match = _rebuild_match(database, run_id)
    summaries = summarize(
        staffing=StaffingResult(rows=rows),
        match=match,
        pack=pack,
        segments=database.query("SELECT * FROM shift_segments WHERE run_id = ?", [run_id]),
    )
    return [
        item.as_dict() for item in summaries if facility is None or item.facility_code == facility
    ]


def _rebuild_match(database: Any, run_id: str) -> Any:
    """Enough of the match result for the summaries, read back from storage."""
    from sot.match.fourway import Coverage, MatchResult, Period, PersonWeek

    weeks = [
        PersonWeek(
            person_id=row["person_id"],
            period=Period(row["period_start"], row["period_end"]),
            facility_code=row["facility_code"] or "",
            role_code=row["role_code"] or "",
            scheduled_work_hours=row["scheduled_work_hours"] or 0.0,
            scheduled_pto_hours=row["scheduled_pto_hours"] or 0.0,
            paid_hours=row["paid_hours"] or 0.0,
            status=row["status"],
            in_both_coverages=bool(row["in_both_coverages"]),
        )
        for row in database.query("SELECT * FROM match_person_week WHERE run_id = ?", [run_id])
    ]
    dates = database.query_one(
        "SELECT min(work_date) AS lo, max(work_date) AS hi FROM shift_segments WHERE run_id = ?",
        [run_id],
    )
    coverage = Coverage(
        schedule=Period(dates["lo"], dates["hi"]) if dates and dates["lo"] else None
    )
    periods = sorted({week.period for week in weeks}, key=lambda item: item.start)
    return MatchResult(weeks=weeks, coverage=coverage, periods=periods)


@router.get("/expirations")
def expirations(
    run_id: str | None = None,
    band: str | None = None,
    facility: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Everything that expires, most urgent first."""
    resolved, run = _context(run_id)
    database = deps.db()
    pack = load_pack(run["pack"])
    as_of = run["as_of"]

    from sot.ledger.golden import Credential
    from sot.views.expirations import build_expirations

    credentials = [
        Credential(
            credential_id=row["credential_id"],
            holder_id=row["holder_id"] or "",
            credential_type=row["credential_type"] or "",
            number=row["number_norm"] or "",
            expires_on=row["expires_on"],
            last_verified=row["last_verified"],
            issued_on=row["issue_date"],
        )
        for row in database.query("SELECT * FROM credentials WHERE run_id = ?", [resolved])
    ]
    people = database.query(
        "SELECT person_id, display_name, home_facility FROM persons WHERE run_id = ?", [resolved]
    )
    view = build_expirations(
        credentials=credentials,
        as_of=as_of,
        pack=pack,
        display_names={row["person_id"]: row["display_name"] for row in people},
        facilities={row["person_id"]: row["home_facility"] or "" for row in people},
        person_days=_person_days(database, resolved),
        pay_lines=_pay_lines(database, resolved),
        vendor_records=database.query(
            "SELECT payload_json FROM std_records WHERE run_id = ? AND source_role = ?",
            [resolved, "vendor_documents"],
        ),
    )
    rows = view.filtered(band=band, facility=facility, kind=kind)
    return {
        "run_id": resolved,
        "as_of": as_of.isoformat() if as_of else None,
        "windows": list(view.windows),
        "counts": view.counts_by_band(),
        "rows": [row.as_dict() for row in rows],
    }


def _person_days(database: Any, run_id: str) -> list[Any]:
    """Person-days read back from storage.

    The three-valued columns are restored too. Leaving them at their default would
    report every credential as unknown, which is the one answer that is never
    harmless: unknown is not green, so the view would say it could not tell.
    """
    from sot.match.fourway import PersonDay
    from sot.tri import Tri

    return [
        PersonDay(
            person_id=row["person_id"],
            work_date=row["work_date"],
            facility_code=row["facility_code"] or "",
            role_code=row["role_code"] or "",
            work_hours=row["work_hours"] or 0.0,
            pto_hours=row["pto_hours"] or 0.0,
            credential_valid=Tri(row["credential_valid"] or "UNKNOWN"),
            employed=Tri(row["employed"] or "UNKNOWN"),
            has_overlap=bool(row["has_overlap"]),
        )
        for row in database.query("SELECT * FROM match_person_day WHERE run_id = ?", [run_id])
    ]


def _pay_lines(database: Any, run_id: str) -> list[Any]:
    from sot.ledger.golden import PayLine

    return [
        PayLine(
            pay_line_id=row["pay_line_id"],
            person_id=row["person_id"] or "",
            facility_code=row["facility_code"] or "",
            role_code=row["role_code"] or "",
            period_start=row["period_start"],
            period_end=row["period_end"],
            hours_paid=row["hours_paid"] or 0.0,
        )
        for row in database.query("SELECT * FROM pay_lines WHERE run_id = ?", [run_id])
    ]


@router.get("/referral")
def referral(
    facility: str,
    work_date: str,
    run_id: str | None = None,
    census: int | None = None,
    plus_one: bool = False,
) -> dict[str, Any]:
    """Can this facility take an admission on this day, and why."""
    resolved, run = _context(run_id)
    database = deps.db()
    pack = load_pack(run["pack"])
    try:
        when = date.fromisoformat(work_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"date must be YYYY-MM-DD, got {work_date!r}"
        ) from None

    segments = database.query("SELECT * FROM shift_segments WHERE run_id = ?", [resolved])
    daily = _daily_rows(database, resolved)
    flags = database.query(
        "SELECT rule_code, message, severity FROM flags WHERE run_id = ?", [resolved]
    )
    people = database.query(
        "SELECT person_id, display_name FROM persons WHERE run_id = ?", [resolved]
    )
    if census is None:
        census = _census_for(database, resolved, facility, when)

    bounds = database.query_one(
        "SELECT min(work_date) AS lo, max(work_date) AS hi FROM shift_segments WHERE run_id = ?",
        [resolved],
    )
    from sot.match.fourway import Period

    coverage = Period(bounds["lo"], bounds["hi"]) if bounds and bounds["lo"] else None

    assessment = assess_referral(
        facility_code=facility,
        work_date=when,
        pack=pack,
        segments=segments,
        person_days=_person_days(database, resolved),
        daily_rows=daily,
        flags=flags,
        display_names={row["person_id"]: row["display_name"] for row in people},
        census=census,
        plus_one=plus_one,
        coverage=coverage,
    )
    return {"run_id": resolved, **assessment.as_dict()}


def _daily_rows(database: Any, run_id: str) -> list[Any]:
    from sot.views.staffing import DailyHours

    return [
        DailyHours(
            facility_code=row["facility_code"],
            work_date=row["work_date"],
            person_id=row["person_id"],
            display_name=row["display_name"] or "",
            role_code=row["role_code"],
            pbj_hours=row["pbj_hours"] or 0.0,
            scheduled_hours=row["scheduled_hours"] or 0.0,
            tier=row["tier"],
        )
        for row in database.query("SELECT * FROM daily_hours WHERE run_id = ?", [run_id])
    ]


def _census_for(database: Any, run_id: str, facility: str, when: date) -> int | None:
    for row in database.query(
        "SELECT payload_json FROM std_records WHERE run_id = ? AND source_role = 'census'",
        [run_id],
    ):
        payload = json.loads(row["payload_json"] or "{}")
        if str(payload.get("facility") or "") != facility:
            continue
        if str(payload.get("date") or "") != when.isoformat():
            continue
        try:
            return int(float(payload.get("residents")))
        except (TypeError, ValueError):
            return None
    return None
