"""Daily staffing hours, in the shape a regulator asks for.

Reported hours are counted by calendar day with midnight as the cut, so a night shift
belongs to two days. Meal time is excluded whether or not it was paid. Neither of
those is how a rota is written, which is exactly why this has to be derived rather
than read off.

Every figure carries a tier saying how much of it is corroborated: hours whose week
reconciles against payroll are verified, hours whose week does not are shown and
flagged rather than hidden, and hours with no payroll at all are marked as what they
are. Paid hours with no rota day are not given one - inventing a date to make a total
balance is the specific thing an audit looks for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sot.canon import canonical_json, round_hours, sum_hours
from sot.match.fourway import (
    STATUS_MATCHED,
    MatchResult,
    PersonWeek,
)
from sot.normalize.shifts import split_at_midnight

TIER_VERIFIED = "VERIFIED"
TIER_CONFLICT = "CONFLICT"
TIER_SCHEDULE_ONLY = "SCHEDULE_ONLY"
TIER_UNALLOCATED = "UNALLOCATED"


@dataclass
class DailyHours:
    """One person's reportable hours at one site on one day."""

    facility_code: str
    work_date: date
    person_id: str
    display_name: str
    role_code: str
    pbj_job_code: str = ""
    scheduled_hours: float = 0.0
    meal_deduction: float = 0.0
    pbj_hours: float = 0.0
    tier: str = TIER_SCHEDULE_ONLY
    segment_ids: tuple[str, ...] = ()
    credential_valid: str = "UNKNOWN"

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "facility_code": self.facility_code,
            "work_date": self.work_date,
            "person_id": self.person_id,
            "display_name": self.display_name,
            "role_code": self.role_code,
            "pbj_job_code": self.pbj_job_code,
            "scheduled_hours": self.scheduled_hours,
            "meal_deduction": self.meal_deduction,
            "pbj_hours": self.pbj_hours,
            "tier": self.tier,
            "evidence_json": canonical_json(
                {"segments": list(self.segment_ids), "credential": self.credential_valid}
            ),
        }


@dataclass
class Unallocated:
    """Paid hours with no rota day to put them on."""

    facility_code: str
    person_id: str
    display_name: str
    period_start: date
    period_end: date
    hours: float


@dataclass
class StaffingResult:
    rows: list[DailyHours] = field(default_factory=list)
    unallocated: list[Unallocated] = field(default_factory=list)
    #: Assumptions applied, shown beside the numbers in the UI.
    assumptions: dict[str, Any] = field(default_factory=dict)

    def by_facility_day(self) -> dict[tuple[str, date], list[DailyHours]]:
        grouped: dict[tuple[str, date], list[DailyHours]] = {}
        for row in self.rows:
            grouped.setdefault((row.facility_code, row.work_date), []).append(row)
        return grouped

    def total(self) -> float:
        return sum_hours(row.pbj_hours for row in self.rows)


def _tier_for(week: PersonWeek | None) -> str:
    if week is None:
        return TIER_SCHEDULE_ONLY
    if week.paid_hours <= 0:
        return TIER_SCHEDULE_ONLY
    if week.status == STATUS_MATCHED:
        return TIER_VERIFIED
    return TIER_CONFLICT


def build_daily_hours(
    *,
    segments: Sequence[Mapping[str, Any]],
    match: MatchResult,
    pack: Any,
    display_names: Mapping[str, str] | None = None,
    pbj_codes: Mapping[str, str] | None = None,
) -> StaffingResult:
    """Turn shift segments into reportable daily hours."""
    display_names = display_names or {}
    pbj_codes = pbj_codes or {}
    split = bool(pack.setting("pbj.split_at_midnight", True))
    include_training = bool(pack.setting("pbj.include_training", False))
    meal = pack.setting("pbj.meal_deduction", {}) or {}
    meal_hours = float(meal.get("minutes", 0) or 0) / 60.0
    meal_minimum = float(meal.get("min_shift_hours", 0) or 0)

    reportable = {"WORK"} | ({"TRAINING"} if include_training else set())
    result = StaffingResult(
        assumptions={
            "split_at_midnight": split,
            "meal_deduction_minutes": meal.get("minutes", 0),
            "meal_applies_from_hours": meal.get("min_shift_hours", 0),
            "training_counted": include_training,
            "attribution": pack.setting("payroll_attribution", "shift_start"),
        }
    )

    weeks_by_key: dict[tuple[str, str], PersonWeek] = {}
    for week in match.weeks:
        for when in _dates_in(week):
            weeks_by_key[(week.person_id, when.isoformat())] = week

    buckets: dict[tuple[str, date, str, str], DailyHours] = {}
    for segment in sorted(segments, key=lambda item: str(item.get("segment_id") or "")):
        if str(segment.get("category") or "") not in reportable:
            continue
        person_id = str(segment.get("person_id") or "")
        facility = str(segment.get("facility_code") or "")
        role = str(segment.get("role_code") or "")
        hours = float(segment.get("hours") or 0.0)
        if not person_id or hours <= 0:
            continue

        parts = _day_parts(segment, hours, split=split)
        # The break is deducted once per shift, on the day the shift began. Where it
        # was actually taken is unknowable from a rota, and splitting it across two
        # days would imply a precision the source does not have.
        deduction = meal_hours if (meal_hours and hours >= meal_minimum) else 0.0

        for index, (when, part_hours) in enumerate(parts):
            key = (facility, when, person_id, role)
            row = buckets.get(key)
            if row is None:
                week = weeks_by_key.get((person_id, when.isoformat()))
                row = DailyHours(
                    facility_code=facility,
                    work_date=when,
                    person_id=person_id,
                    display_name=display_names.get(person_id, person_id),
                    role_code=role,
                    pbj_job_code=pbj_codes.get(role.upper(), ""),
                    tier=_tier_for(week),
                )
                buckets[key] = row
            row.scheduled_hours = round_hours(row.scheduled_hours + part_hours) or 0.0
            if index == 0:
                row.meal_deduction = round_hours(row.meal_deduction + deduction) or 0.0
            row.segment_ids = (*row.segment_ids, str(segment.get("segment_id") or ""))

    for row in buckets.values():
        row.pbj_hours = max(round_hours(row.scheduled_hours - row.meal_deduction) or 0.0, 0.0)

    result.rows = sorted(
        buckets.values(),
        key=lambda item: (item.facility_code, item.work_date, item.person_id, item.role_code),
    )
    result.unallocated = _unallocated(match, display_names)
    return result


def _dates_in(week: PersonWeek) -> list[date]:
    from datetime import timedelta

    days = (week.period.end - week.period.start).days
    return [week.period.start + timedelta(days=offset) for offset in range(days + 1)]


def _day_parts(
    segment: Mapping[str, Any], hours: float, *, split: bool
) -> list[tuple[date, float]]:
    """Which calendar days a segment's hours belong to."""
    work_date = segment.get("work_date")
    if isinstance(work_date, datetime):
        work_date = work_date.date()
    start, end = segment.get("start_ts"), segment.get("end_ts")
    if not split or start is None or end is None:
        return [(work_date, round_hours(hours) or 0.0)] if work_date else []
    parts = split_at_midnight(start, end, hours)
    return parts or ([(work_date, round_hours(hours) or 0.0)] if work_date else [])


def _unallocated(match: MatchResult, display_names: Mapping[str, str]) -> list[Unallocated]:
    """Paid hours with no rota day.

    Reported as their own figure rather than spread across the period. Inventing a
    date to make a total balance is the specific thing an audit looks for.
    """
    found: list[Unallocated] = []
    for week in match.weeks:
        if week.paid_hours <= 0 or week.scheduled_work_hours > 0:
            continue
        if not week.in_both_coverages:
            continue
        found.append(
            Unallocated(
                facility_code=week.facility_code,
                person_id=week.person_id,
                display_name=display_names.get(week.person_id, week.person_id),
                period_start=week.period.start,
                period_end=week.period.end,
                hours=week.paid_hours,
            )
        )
    return found
