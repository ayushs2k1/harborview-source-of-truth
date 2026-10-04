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
    day_intervals,
    role_family,
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


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

#: Federal fiscal quarters. Reported staffing is grouped and filed on these, which
#: are not calendar quarters - a detail that is easy to get wrong and expensive to.
_FISCAL_QUARTERS = {
    "Q1": (10, 12),
    "Q2": (1, 3),
    "Q3": (4, 6),
    "Q4": (7, 9),
}
_MONTH_TO_QUARTER = {
    month: name
    for name, (start, end) in _FISCAL_QUARTERS.items()
    for month in ([10, 11, 12] if name == "Q1" else list(range(start, end + 1)))
}

#: Days after a quarter ends before the submission is due.
FILING_DAYS = 45


@dataclass(frozen=True)
class Quarter:
    """A federal fiscal quarter and when its submission is due."""

    label: str
    start: date
    end: date
    due: date

    @property
    def description(self) -> str:
        span = f"{self.start:%b}\u2013{self.end:%b}"
        return f"{self.label} ({span}), due {self.due:%b} {self.due.day}, {self.due.year}"


def quarter_for(when: date, *, filing_days: int = FILING_DAYS) -> Quarter:
    """The fiscal quarter containing a date, and its filing deadline.

    Federal fiscal quarters, not calendar ones: the year rolls over in October, so
    a shift worked in October 2026 is filed under FFY2027. Easy to get wrong, and
    expensive to - the deadline moves by three months.
    """
    import calendar
    from datetime import timedelta

    name = _MONTH_TO_QUARTER[when.month]
    first_month, last_month = _FISCAL_QUARTERS[name]
    fiscal_year = when.year + 1 if when.month >= 10 else when.year
    start_year = fiscal_year - 1 if name == "Q1" else fiscal_year
    start = date(start_year, first_month, 1)
    end = date(start_year, last_month, calendar.monthrange(start_year, last_month)[1])
    return Quarter(f"FFY{fiscal_year} {name}", start, end, end + timedelta(days=filing_days))


@dataclass
class FacilitySummary:
    """One facility over one period, in the shape the quarterly filing needs."""

    facility_code: str
    facility_name: str
    period_start: date
    period_end: date
    hours_by_role: dict[str, float] = field(default_factory=dict)
    total_hours: float = 0.0
    verified_hours: float = 0.0
    conflict_hours: float = 0.0
    schedule_only_hours: float = 0.0
    unallocated_hours: float = 0.0
    zero_rn_days: int = 0
    zero_rn_warn: int = 0
    zero_rn_critical: int = 0
    cap_violations: int = 0
    traceability_variance_pct: float = 0.0
    traceability_threshold: float = 4.0
    quarter: Quarter | None = None

    @property
    def pct_verified(self) -> float:
        return round((self.verified_hours / self.total_hours * 100) if self.total_hours else 0.0, 1)

    @property
    def pct_unallocated(self) -> float:
        base = self.total_hours + self.unallocated_hours
        return round((self.unallocated_hours / base * 100) if base else 0.0, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "facility_code": self.facility_code,
            "facility": self.facility_name,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "hours_by_role": self.hours_by_role,
            "total_hours": self.total_hours,
            "verified_hours": self.verified_hours,
            "conflict_hours": self.conflict_hours,
            "schedule_only_hours": self.schedule_only_hours,
            "unallocated_hours": self.unallocated_hours,
            "pct_verified": self.pct_verified,
            "pct_unallocated": self.pct_unallocated,
            "zero_rn_days": self.zero_rn_days,
            "zero_rn_warn": self.zero_rn_warn,
            "zero_rn_critical": self.zero_rn_critical,
            "cap_violations": self.cap_violations,
            "traceability_variance_pct": self.traceability_variance_pct,
            "traceability_threshold": self.traceability_threshold,
            "quarter": self.quarter.description if self.quarter else None,
            "quarter_due": self.quarter.due.isoformat() if self.quarter else None,
        }


def summarize(
    *,
    staffing: StaffingResult,
    match: MatchResult,
    pack: Any,
    segments: Sequence[Mapping[str, Any]] = (),
) -> list[FacilitySummary]:
    """One summary per facility per period."""
    rn_intervals = day_intervals(segments, role_family(pack, "nurse_rn"))
    cap = float(pack.setting("pbj.daily_cap_hours", 22.5) or 22.5)
    zero_rn = pack.setting("zero_rn_days", {}) or {}
    threshold = float(pack.setting("pbj.traceability_variance_pct", 4.0) or 4.0)
    crosswalk = pack.crosswalk("facilities") if hasattr(pack, "crosswalk") else None
    names = {entry.code: entry.name for entry in crosswalk.entries} if crosswalk else {}

    periods_by_date: dict[date, Any] = {}
    for period in match.periods:
        day = period.start
        while day <= period.end:
            periods_by_date[day] = period
            day = date.fromordinal(day.toordinal() + 1)

    summaries: dict[tuple[str, date], FacilitySummary] = {}

    def summary_for(facility: str, when: date) -> FacilitySummary | None:
        period = periods_by_date.get(when)
        if period is None:
            return None
        key = (facility, period.start)
        if key not in summaries:
            summaries[key] = FacilitySummary(
                facility_code=facility,
                facility_name=names.get(facility) or facility or "(unrecorded site)",
                period_start=period.start,
                period_end=period.end,
                zero_rn_warn=int(zero_rn.get("warn", 4) or 4),
                zero_rn_critical=int(zero_rn.get("critical", 7) or 7),
                traceability_threshold=threshold,
                quarter=quarter_for(period.start),
            )
        return summaries[key]

    daily_totals: dict[tuple[str, date, str], float] = {}
    for row in staffing.rows:
        summary = summary_for(row.facility_code, row.work_date)
        if summary is None:
            continue
        summary.total_hours = round_hours(summary.total_hours + row.pbj_hours) or 0.0
        summary.hours_by_role[row.role_code] = (
            round_hours(summary.hours_by_role.get(row.role_code, 0.0) + row.pbj_hours) or 0.0
        )
        if row.tier == TIER_VERIFIED:
            summary.verified_hours = round_hours(summary.verified_hours + row.pbj_hours) or 0.0
        elif row.tier == TIER_CONFLICT:
            summary.conflict_hours = round_hours(summary.conflict_hours + row.pbj_hours) or 0.0
        else:
            summary.schedule_only_hours = (
                round_hours(summary.schedule_only_hours + row.pbj_hours) or 0.0
            )
        key = (row.facility_code, row.work_date, row.person_id)
        daily_totals[key] = round_hours(daily_totals.get(key, 0.0) + row.scheduled_hours) or 0.0

    for item in staffing.unallocated:
        summary = summary_for(item.facility_code, item.period_start)
        if summary is not None:
            summary.unallocated_hours = round_hours(summary.unallocated_hours + item.hours) or 0.0

    for (facility, when, _person), hours in daily_totals.items():
        if hours > cap:
            summary = summary_for(facility, when)
            if summary is not None:
                summary.cap_violations += 1

    coverage = match.coverage.schedule
    if coverage is not None:
        for summary in summaries.values():
            day = max(summary.period_start, coverage.start)
            last = min(summary.period_end, coverage.end)
            while day <= last:
                if not rn_intervals.get((summary.facility_code, day)):
                    summary.zero_rn_days += 1
                day = date.fromordinal(day.toordinal() + 1)

    totals: dict[tuple[str, date], list[float]] = {}
    for week in match.weeks:
        if not week.in_both_coverages:
            continue
        key = (week.facility_code, week.period.start)
        scheduled, paid, pto = totals.get(key, [0.0, 0.0, 0.0])
        totals[key] = [
            scheduled + week.scheduled_work_hours,
            paid + week.paid_hours,
            pto + week.scheduled_pto_hours,
        ]
    for key, (scheduled, paid, pto) in totals.items():
        summary = summaries.get(key)
        if summary is None:
            continue
        comparable = round_hours(paid - pto) or 0.0
        base = max(scheduled, comparable)
        summary.traceability_variance_pct = (
            round(abs(scheduled - comparable) / base * 100, 1) if base else 0.0
        )

    return sorted(
        summaries.values(),
        key=lambda item: (item.facility_code, item.period_start),
    )
