"""The four-way match.

Four systems each answer a different question about the same week. The schedule says
what was *planned*, payroll says what was *paid*, the roster says who was *employed*,
and the credential service says who was *permitted*. Agreement between all four is the
only state that needs no explanation; every other combination is a finding.

Two grains. The person-week is where money is reconciled, because payroll thinks in
pay periods. The person-day is where compliance lives, because a credential either
covered the day somebody worked or it did not.

Coverage is established before anything is compared. If payroll covers three weeks and
the rota covers one, the two weeks payroll alone knows about are not everybody failing
to turn up - they are weeks nobody sent us a rota for, and that is one finding rather
than one per person.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sot.canon import round_hours, sum_hours
from sot.ledger.golden import Credential, Golden, PayLine
from sot.tri import Tri, from_bool, tri_all

STATUS_MATCHED = "MATCHED"
STATUS_HOURS_VARIANCE = "HOURS_VARIANCE"
STATUS_PAID_NOT_SCHEDULED = "PAID_NOT_SCHEDULED"
STATUS_SCHEDULED_NOT_PAID = "SCHEDULED_NOT_PAID"
STATUS_NOT_EMPLOYED = "NOT_EMPLOYED"
STATUS_NOT_PERMITTED = "NOT_PERMITTED"
STATUS_UNKNOWN = "UNKNOWN"

DIRECTION_PAID_MORE = "PAID_MORE"
DIRECTION_PAID_LESS = "PAID_LESS"

#: Categories that count as time worked when reconciling against payroll.
WORKED_CATEGORIES = frozenset({"WORK", "TRAINING"})

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def contains(self, when: date) -> bool:
        return self.start <= when <= self.end

    def overlaps(self, other: Period) -> bool:
        return self.start <= other.end and other.start <= self.end

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class Coverage:
    """What each source actually tells us about."""

    schedule: Period | None = None
    payroll: Period | None = None

    @property
    def both(self) -> Period | None:
        if self.schedule is None or self.payroll is None:
            return None
        start = max(self.schedule.start, self.payroll.start)
        end = min(self.schedule.end, self.payroll.end)
        return Period(start, end) if start <= end else None

    def comparable(self, period: Period) -> bool:
        """True when both sources have something to say about this period."""
        overlap = self.both
        return overlap is not None and period.overlaps(overlap)


@dataclass
class PersonWeek:
    """One person, one pay period, one site."""

    person_id: str
    period: Period
    facility_code: str
    role_code: str = ""
    scheduled_work_hours: float = 0.0
    scheduled_pto_hours: float = 0.0
    paid_hours: float = 0.0
    employed: Tri = Tri.UNKNOWN
    permitted: Tri = Tri.UNKNOWN
    status: str = STATUS_UNKNOWN
    direction: str = ""
    explained_by_pto: bool = False
    in_both_coverages: bool = True
    pay_line_ids: tuple[str, ...] = ()
    segment_ids: tuple[str, ...] = ()
    worked_dates: tuple[date, ...] = ()

    @property
    def delta(self) -> float:
        return round_hours(self.paid_hours - self.scheduled_work_hours) or 0.0

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "person_id": self.person_id,
            "period_start": self.period.start,
            "period_end": self.period.end,
            "facility_code": self.facility_code,
            "role_code": self.role_code,
            "scheduled_work_hours": self.scheduled_work_hours,
            "scheduled_pto_hours": self.scheduled_pto_hours,
            "paid_hours": self.paid_hours,
            "delta": self.delta,
            "employed": str(self.employed),
            "permitted": str(self.permitted),
            "status": self.status,
            "direction": self.direction,
            "explained_by_pto": self.explained_by_pto,
            "in_both_coverages": self.in_both_coverages,
        }


@dataclass
class PersonDay:
    """One person, one date, one site. Where compliance is judged."""

    person_id: str
    work_date: date
    facility_code: str
    role_code: str = ""
    work_hours: float = 0.0
    pto_hours: float = 0.0
    segment_ids: tuple[str, ...] = ()
    credential_valid: Tri = Tri.UNKNOWN
    employed: Tri = Tri.UNKNOWN
    has_overlap: bool = False

    def as_row(self, run_id: str) -> dict[str, Any]:
        from sot.canon import canonical_json

        return {
            "run_id": run_id,
            "person_id": self.person_id,
            "work_date": self.work_date,
            "facility_code": self.facility_code,
            "role_code": self.role_code,
            "work_hours": self.work_hours,
            "pto_hours": self.pto_hours,
            "segment_ids_json": canonical_json(list(self.segment_ids)),
            "credential_valid": str(self.credential_valid),
            "employed": str(self.employed),
            "has_overlap": self.has_overlap,
        }


@dataclass
class MatchResult:
    weeks: list[PersonWeek] = field(default_factory=list)
    days: list[PersonDay] = field(default_factory=list)
    coverage: Coverage = field(default_factory=Coverage)
    periods: list[Period] = field(default_factory=list)
    #: Periods payroll knows about that the rota does not, and the other way round.
    uncovered: list[Period] = field(default_factory=list)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def week_containing(when: date, week_start: str = "monday") -> Period:
    """The pack's week containing a date."""
    start_index = _WEEKDAYS.get(str(week_start).lower(), 0)
    offset = (when.weekday() - start_index) % 7
    start = when - timedelta(days=offset)
    return Period(start, start + timedelta(days=6))


def build_coverage(pay_lines: Sequence[PayLine], segments: Sequence[Mapping[str, Any]]) -> Coverage:
    """What each source covers, from the data rather than from an assumption."""
    pay_dates = [line.period_start for line in pay_lines if line.period_start]
    pay_ends = [line.period_end for line in pay_lines if line.period_end]
    work_dates = [d for d in (_as_date(s.get("work_date")) for s in segments) if d]
    return Coverage(
        schedule=Period(min(work_dates), max(work_dates)) if work_dates else None,
        payroll=Period(min(pay_dates), max(pay_ends)) if pay_dates and pay_ends else None,
    )


def build_periods(
    pay_lines: Sequence[PayLine],
    segments: Sequence[Mapping[str, Any]],
    *,
    week_start: str = "monday",
) -> list[Period]:
    """Every period worth reconciling.

    Payroll's own periods are used where it has them, because that is the unit it
    pays in. Rota dates falling outside all of them get the pack's calendar week, so
    work in a week payroll has not reached is still accounted for.
    """
    periods = {
        Period(line.period_start, line.period_end)
        for line in pay_lines
        if line.period_start and line.period_end
    }
    for segment in segments:
        when = _as_date(segment.get("work_date"))
        if when is None or any(period.contains(when) for period in periods):
            continue
        periods.add(week_containing(when, week_start))
    return sorted(periods, key=lambda period: (period.start, period.end))


def required_credential_types(pack_setting: Mapping[str, Any], role: str) -> tuple[str, ...]:
    """Credential types that satisfy a role, per the pack."""
    values = (pack_setting or {}).get(role.upper()) if role else None
    if not values:
        return ()
    return tuple(str(item).upper() for item in values)


def run_match(
    *,
    persons: Sequence[Any],
    pay_lines: Sequence[PayLine],
    segments: Sequence[Mapping[str, Any]],
    credentials: Sequence[Credential],
    golden: Golden,
    required_credential: Mapping[str, Any],
    week_start: str = "monday",
    tolerance: float = 0.25,
) -> MatchResult:
    """Reconcile planned, paid, employed and permitted."""
    result = MatchResult()
    result.coverage = build_coverage(pay_lines, segments)
    result.periods = build_periods(pay_lines, segments, week_start=week_start)

    credentials_by_holder: dict[str, list[Credential]] = {}
    for credential in credentials:
        if credential.holder_id:
            credentials_by_holder.setdefault(credential.holder_id, []).append(credential)

    result.days = _build_days(segments, golden, credentials_by_holder, required_credential)
    days_by_person: dict[str, list[PersonDay]] = {}
    for day in result.days:
        days_by_person.setdefault(day.person_id, []).append(day)

    result.weeks = _build_weeks(
        persons=persons,
        pay_lines=pay_lines,
        segments=segments,
        periods=result.periods,
        coverage=result.coverage,
        golden=golden,
        days_by_person=days_by_person,
        tolerance=tolerance,
    )
    overlap = result.coverage.both
    result.uncovered = [
        period for period in result.periods if overlap is None or not period.overlaps(overlap)
    ]
    return result


def _employed_on(golden: Golden, person_id: str, start: date, end: date) -> Tri:
    """Whether somebody was on the books across a span.

    Unknown rather than false when there is no hire date: "we have no record of when
    they started" is a different statement from "they did not work here".
    """
    hire = golden.person_date(person_id, "hire_date")
    termination = golden.person_date(person_id, "termination_date")
    if hire is None:
        return Tri.UNKNOWN
    if hire > end:
        return Tri.FAIL
    if termination is not None and termination < start:
        return Tri.FAIL
    return Tri.PASS


def _credential_valid_on(
    credentials: Sequence[Credential],
    when: date,
    role: str,
    required: Mapping[str, Any],
) -> Tri:
    """Whether a valid credential of a sufficient type covered a date."""
    accepted = required_credential_types(required, role)
    if not role:
        return Tri.UNKNOWN
    if not accepted:
        return Tri.PASS  # the role needs nothing, so nothing is missing
    relevant = [
        credential
        for credential in credentials
        if (credential.credential_type or "").upper() in accepted
    ]
    if not relevant:
        return Tri.FAIL
    verdicts = [from_bool(credential.valid_on(when)) for credential in relevant]
    if any(verdict is Tri.PASS for verdict in verdicts):
        return Tri.PASS
    if all(verdict is Tri.UNKNOWN for verdict in verdicts):
        return Tri.UNKNOWN
    return Tri.FAIL


def _build_days(
    segments: Sequence[Mapping[str, Any]],
    golden: Golden,
    credentials_by_holder: Mapping[str, list[Credential]],
    required_credential: Mapping[str, Any],
) -> list[PersonDay]:
    """One row per person per date per site."""
    grouped: dict[tuple[str, date, str, str], list[Mapping[str, Any]]] = {}
    for segment in segments:
        person_id = str(segment.get("person_id") or "")
        when = _as_date(segment.get("work_date"))
        if not person_id or when is None:
            continue
        key = (
            person_id,
            when,
            str(segment.get("facility_code") or ""),
            str(segment.get("role_code") or ""),
        )
        grouped.setdefault(key, []).append(segment)

    overlaps = _overlapping_person_days(segments)
    days: list[PersonDay] = []
    for key, group in sorted(grouped.items()):
        person_id, when, facility, role = key
        work = sum_hours(
            item.get("hours") for item in group if item.get("category") in WORKED_CATEGORIES
        )
        pto = sum_hours(item.get("hours") for item in group if item.get("category") == "PTO")
        days.append(
            PersonDay(
                person_id=person_id,
                work_date=when,
                facility_code=facility,
                role_code=role,
                work_hours=work,
                pto_hours=pto,
                segment_ids=tuple(sorted(str(item["segment_id"]) for item in group)),
                credential_valid=_credential_valid_on(
                    credentials_by_holder.get(person_id, ()), when, role, required_credential
                ),
                employed=_employed_on(golden, person_id, when, when),
                has_overlap=(person_id, when) in overlaps,
            )
        )
    return days


def _overlapping_person_days(segments: Sequence[Mapping[str, Any]]) -> set[tuple[str, date]]:
    """Person-days where two segments claim the same clock time.

    Checked across sites as well as within one: the same person at two facilities at
    once is the version of this that matters.
    """
    by_person: dict[str, list[tuple[datetime, datetime, str]]] = {}
    for segment in segments:
        person_id = str(segment.get("person_id") or "")
        start, end = segment.get("start_ts"), segment.get("end_ts")
        if not person_id or start is None or end is None:
            continue
        by_person.setdefault(person_id, []).append(
            (start, end, str(segment.get("segment_id") or ""))
        )

    found: set[tuple[str, date]] = set()
    for person_id, spans in sorted(by_person.items()):
        spans.sort()
        for index in range(len(spans) - 1):
            current_end = spans[index][1]
            next_start = spans[index + 1][0]
            if next_start < current_end:
                found.add((person_id, spans[index][0].date()))
                found.add((person_id, next_start.date()))
    return found


def _build_weeks(
    *,
    persons: Sequence[Any],
    pay_lines: Sequence[PayLine],
    segments: Sequence[Mapping[str, Any]],
    periods: Sequence[Period],
    coverage: Coverage,
    golden: Golden,
    days_by_person: Mapping[str, list[PersonDay]],
    tolerance: float,
) -> list[PersonWeek]:
    """One row per person per period per site, with a single primary status."""
    buckets: dict[tuple[str, date, str], PersonWeek] = {}

    def bucket(person_id: str, period: Period, facility: str) -> PersonWeek:
        key = (person_id, period.start, facility)
        if key not in buckets:
            buckets[key] = PersonWeek(
                person_id=person_id,
                period=period,
                facility_code=facility,
                in_both_coverages=coverage.comparable(period),
            )
        return buckets[key]

    def period_for(when: date) -> Period | None:
        return next((period for period in periods if period.contains(when)), None)

    for line in pay_lines:
        if not line.person_id or not line.period_start:
            continue
        period = period_for(line.period_start) or Period(
            line.period_start, line.period_end or line.period_start
        )
        week = bucket(line.person_id, period, line.facility_code)
        week.paid_hours = round_hours(week.paid_hours + line.hours_paid) or 0.0
        week.pay_line_ids = (*week.pay_line_ids, line.pay_line_id)
        if not week.role_code:
            week.role_code = line.role_code

    for segment in segments:
        person_id = str(segment.get("person_id") or "")
        when = _as_date(segment.get("work_date"))
        if not person_id or when is None:
            continue
        period = period_for(when)
        if period is None:
            continue
        week = bucket(person_id, period, str(segment.get("facility_code") or ""))
        hours = float(segment.get("hours") or 0.0)
        category = str(segment.get("category") or "")
        if category in WORKED_CATEGORIES:
            week.scheduled_work_hours = round_hours(week.scheduled_work_hours + hours) or 0.0
            week.worked_dates = (*week.worked_dates, when)
        elif category == "PTO":
            week.scheduled_pto_hours = round_hours(week.scheduled_pto_hours + hours) or 0.0
        week.segment_ids = (*week.segment_ids, str(segment.get("segment_id") or ""))
        role = str(segment.get("role_code") or "")
        if role:
            # The rota is what happened, so it wins the role on the week.
            week.role_code = role

    for week in buckets.values():
        week.worked_dates = tuple(sorted(set(week.worked_dates)))
        week.employed = _employed_on(golden, week.person_id, week.period.start, week.period.end)
        week.permitted = _permitted_for(week, days_by_person.get(week.person_id, ()))
        _set_status(week, tolerance)

    return sorted(
        buckets.values(),
        key=lambda week: (week.person_id, week.period.start, week.facility_code),
    )


def _permitted_for(week: PersonWeek, days: Iterable[PersonDay]) -> Tri:
    """Every worked day in the week covered by a valid credential."""
    relevant = [
        day
        for day in days
        if week.period.contains(day.work_date)
        and day.facility_code == week.facility_code
        and day.work_hours > 0
    ]
    if not relevant:
        return Tri.UNKNOWN
    return tri_all(day.credential_valid for day in relevant)


def _set_status(week: PersonWeek, tolerance: float) -> None:
    """Exactly one primary status, worst first.

    Working while not employed or not permitted outranks any arithmetic: a week that
    reconciles perfectly is still a problem if the person should not have been there.
    """
    worked = week.scheduled_work_hours > 0
    paid = week.paid_hours > 0

    if worked and week.employed is Tri.FAIL:
        week.status = STATUS_NOT_EMPLOYED
        return
    if worked and week.permitted is Tri.FAIL:
        week.status = STATUS_NOT_PERMITTED
        return

    if paid and not worked:
        week.status = STATUS_PAID_NOT_SCHEDULED if week.in_both_coverages else STATUS_UNKNOWN
        return
    if worked and not paid:
        week.status = STATUS_SCHEDULED_NOT_PAID if week.in_both_coverages else STATUS_UNKNOWN
        return
    if not worked and not paid:
        week.status = STATUS_UNKNOWN
        return

    delta = week.delta
    if abs(delta) <= tolerance:
        week.status = STATUS_MATCHED
        return

    # Paid leave on the rota accounts for the gap: the week reconciles once the leave
    # is counted, so this is explained rather than wrong.
    if week.scheduled_pto_hours > 0 and abs(delta - week.scheduled_pto_hours) <= tolerance:
        week.explained_by_pto = True

    week.status = STATUS_HOURS_VARIANCE
    week.direction = DIRECTION_PAID_MORE if delta > 0 else DIRECTION_PAID_LESS


# ---------------------------------------------------------------------------
# Shared segment helpers
# ---------------------------------------------------------------------------


def role_family(pack: Any, name: str) -> set[str]:
    """Role codes belonging to one of the pack's role families."""
    families = pack.setting("role_families", {}) or {}
    return {str(role).upper() for role in families.get(name, ())}


def day_intervals(
    segments: Sequence[Mapping[str, Any]], roles: set[str]
) -> dict[tuple[str, date], list[tuple[float, float]]]:
    """Hours-from-midnight intervals per facility-day, for the given roles.

    Computed from the clock rather than from daily totals, because coverage rules are
    about an unbroken stretch. Two nurses working four hours each is eight hours of
    nursing and may still leave the building uncovered.
    """
    spans: dict[tuple[str, date], list[tuple[float, float]]] = {}
    for segment in segments:
        if str(segment.get("category") or "") not in WORKED_CATEGORIES:
            continue
        if str(segment.get("role_code") or "").upper() not in roles:
            continue
        start, end = segment.get("start_ts"), segment.get("end_ts")
        facility = str(segment.get("facility_code") or "")
        if start is None or end is None or not facility:
            continue
        cursor = start
        while cursor < end:
            day = cursor.date()
            midnight = datetime.combine(day + timedelta(days=1), datetime.min.time())
            boundary = min(midnight, end)
            from_hour = cursor.hour + cursor.minute / 60.0
            to_hour = (boundary - datetime.combine(day, datetime.min.time())).total_seconds() / 3600
            spans.setdefault((facility, day), []).append((from_hour, to_hour))
            cursor = boundary
    return spans


def longest_run(intervals: Sequence[tuple[float, float]]) -> float:
    """Longest unbroken stretch covered by a union of intervals."""
    if not intervals:
        return 0.0
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return round_hours(max(end - start for start, end in merged)) or 0.0
