"""Rules specific to skilled nursing in New York.

Every threshold here comes from the pack, with its source cited beside it. None of
these numbers is compiled in: if a judge disputes one, it is changed in a YAML file
and the run is repeated.

What makes these domain rules rather than engine rules is that they encode what the
regulator asks for - an RN on duty for a stretch rather than for a total, hours per
resident rather than hours, certified aide hours rather than aide hours. The engine
supplies the hours; the pack decides what they have to add up to.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sot.canon import round_hours, sum_hours
from sot.rules.engine import RuleContext, evaluator
from sot.rules.model import Finding

#: Federal fiscal quarters, which is how reported staffing is grouped.
_FISCAL_QUARTER = {
    10: "Q1",
    11: "Q1",
    12: "Q1",
    1: "Q2",
    2: "Q2",
    3: "Q2",
    4: "Q3",
    5: "Q3",
    6: "Q3",
    7: "Q4",
    8: "Q4",
    9: "Q4",
}


def quarter_label(when: date) -> str:
    """The federal fiscal quarter a date falls in, e.g. ``FFY2027 Q1``."""
    quarter = _FISCAL_QUARTER[when.month]
    year = when.year + 1 if when.month >= 10 else when.year
    return f"FFY{year} {quarter}"


def _family(context: RuleContext, name: str) -> set[str]:
    families = context.setting("role_families", {}) or {}
    return {str(role).upper() for role in families.get(name, ())}


def _rn_roles(context: RuleContext) -> set[str]:
    return _family(context, "nurse_rn")


def _licensed_roles(context: RuleContext) -> set[str]:
    return _rn_roles(context) | _family(context, "nurse_lpn")


def _aide_roles(context: RuleContext) -> set[str]:
    return _family(context, "aide")


def _day_intervals(
    segments: Sequence[Mapping[str, Any]], roles: set[str]
) -> dict[tuple[str, date], list[tuple[float, float]]]:
    """Hours-from-midnight intervals per facility-day, for the given roles.

    Computed from the clock rather than from daily totals, because the rule is about
    an unbroken stretch of cover. Two nurses working four hours each is eight hours of
    nursing and may still leave the building uncovered.
    """
    spans: dict[tuple[str, date], list[tuple[float, float]]] = {}
    for segment in segments:
        if str(segment.get("category") or "") not in {"WORK", "TRAINING"}:
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


def _covered_days(context: RuleContext) -> list[tuple[str, date]]:
    """Facility-days the rota actually covers.

    Only these are judged. A day nobody sent us a rota for is not a day with no nurse
    on it, and reporting it as one would bury the days that really are uncovered.
    """
    coverage = context.match.coverage.schedule
    if coverage is None:
        return []
    facilities = sorted(
        {
            str(segment.get("facility_code") or "")
            for segment in context.segments
            if segment.get("facility_code")
        }
    )
    days = (coverage.end - coverage.start).days
    return [
        (facility, coverage.start + timedelta(days=offset))
        for facility in facilities
        for offset in range(days + 1)
    ]


@evaluator("RN_8H_COVERAGE_GAP")
def rn_coverage(context: RuleContext) -> Iterable[Finding]:
    """An RN on duty for a stretch, not merely for a total."""
    required = float(context.setting("rn_min_consecutive_hours", 8) or 8)
    mode = str(context.setting("rn_coverage_mode", "union") or "union")
    rn_roles = _rn_roles(context)
    if not rn_roles:
        return

    if mode == "single_person":
        spans: dict[tuple[str, date], list[tuple[float, float]]] = {}
        for segment in context.segments:
            person = str(segment.get("person_id") or "")
            if not person:
                continue
            for key, values in _day_intervals([segment], rn_roles).items():
                spans.setdefault((*key, person), []).extend(values)  # type: ignore[arg-type]
        best: dict[tuple[str, date], float] = {}
        for key, values in spans.items():
            facility_day = (key[0], key[1])
            best[facility_day] = max(best.get(facility_day, 0.0), longest_run(values))
    else:
        intervals = _day_intervals(context.segments, rn_roles)
        best = {key: longest_run(values) for key, values in intervals.items()}

    for facility, day in _covered_days(context):
        covered = best.get((facility, day), 0.0)
        if covered >= required:
            continue
        yield Finding(
            "RN_8H_COVERAGE_GAP",
            {
                "facility": context.facility_name(facility),
                "work_date": day,
                "required": required,
                "actual": (
                    f"the longest unbroken stretch is {covered} hours"
                    if covered
                    else "no RN hours at all"
                ),
            },
            key_parts=(facility, day.isoformat()),
        )


@evaluator("ZERO_RN_DAYS_QUARTER")
def zero_rn_days(context: RuleContext) -> Iterable[Finding]:
    """Days with no RN hours at all, counted per facility per quarter."""
    thresholds = context.setting("zero_rn_days", {}) or {}
    warn = int(thresholds.get("warn", 4) or 4)
    critical = int(thresholds.get("critical", 7) or 7)
    rn_roles = _rn_roles(context)
    intervals = _day_intervals(context.segments, rn_roles)

    counts: dict[tuple[str, str], int] = {}
    for facility, day in _covered_days(context):
        if intervals.get((facility, day)):
            continue
        counts[(facility, quarter_label(day))] = counts.get((facility, quarter_label(day)), 0) + 1

    for (facility, quarter), days in sorted(counts.items()):
        if days < warn:
            continue
        yield Finding(
            "ZERO_RN_DAYS_QUARTER",
            {
                "facility": context.facility_name(facility),
                "days": days,
                "quarter": quarter,
                "critical_threshold": critical,
            },
            key_parts=(facility, quarter),
        )


@evaluator("PBJ_TRACEABILITY_VARIANCE")
def traceability_variance(context: RuleContext) -> Iterable[Finding]:
    """Whether the hours we would report could be traced back to payroll.

    Audits compare a submission against payroll. A gap between the rota and what was
    paid is the gap an auditor will find, so it is measured before anybody submits.
    """
    threshold = float(context.setting("pbj.traceability_variance_pct", 4.0) or 4.0)
    totals: dict[tuple[str, date, date], list[float]] = {}
    for week in context.match.weeks:
        if not week.in_both_coverages:
            continue
        key = (week.facility_code, week.period.start, week.period.end)
        scheduled, paid, pto = totals.get(key, [0.0, 0.0, 0.0])
        totals[key] = [
            scheduled + week.scheduled_work_hours,
            paid + week.paid_hours,
            pto + week.scheduled_pto_hours,
        ]

    for (facility, start, end), (scheduled, paid, pto) in sorted(totals.items()):
        comparable = round_hours(paid - pto) or 0.0
        base = max(scheduled, comparable)
        if base <= 0:
            continue
        variance = abs(scheduled - comparable) / base * 100
        if variance <= threshold:
            continue
        yield Finding(
            "PBJ_TRACEABILITY_VARIANCE",
            {
                "facility": context.facility_name(facility) if facility else "an unrecorded site",
                "period_start": start,
                "period_end": end,
                "scheduled_hours": round_hours(scheduled),
                "paid_hours": comparable,
                "variance_pct": variance,
                "threshold": threshold,
            },
            key_parts=(facility, start.isoformat()),
        )


@evaluator("HPRD_BELOW_MINIMUM")
def hours_per_resident_day(context: RuleContext) -> Iterable[Finding]:
    """Staffing measured against the people being cared for.

    Only runs when a census was supplied. Without one the ratio is unknowable, and
    the three-valued rule says unknown rather than guessing at a denominator.
    """
    if not context.census:
        return
    minimums = context.setting("hprd_minimums", {}) or {}
    if not minimums:
        return

    rn_roles, licensed, aides = _rn_roles(context), _licensed_roles(context), _aide_roles(context)
    del rn_roles
    by_day: dict[tuple[str, date], dict[str, float]] = {}
    for row in context.daily_hours.rows if hasattr(context.daily_hours, "rows") else ():
        bucket = by_day.setdefault((row.facility_code, row.work_date), {})
        bucket["total"] = bucket.get("total", 0.0) + row.pbj_hours
        role = row.role_code.upper()
        if role in licensed:
            bucket["licensed"] = bucket.get("licensed", 0.0) + row.pbj_hours
        if role in aides:
            bucket["cna"] = bucket.get("cna", 0.0) + row.pbj_hours

    # Reported per facility and staffing category rather than per day. A week below
    # the minimum is one problem with seven dates, and forty-odd identical cards would
    # bury everything else in the inbox.
    worst: dict[tuple[str, str], tuple[float, date, int, int]] = {}
    for (facility, day), buckets in sorted(by_day.items()):
        residents = context.census.get((facility, day))
        if not residents:
            continue
        for bucket, minimum in sorted(minimums.items()):
            actual = round_hours(buckets.get(bucket, 0.0) / residents) or 0.0
            if actual >= float(minimum):
                continue
            key = (facility, bucket)
            previous = worst.get(key)
            if previous is None or actual < previous[0]:
                worst[key] = (actual, day, residents, (previous[3] if previous else 0) + 1)
            else:
                worst[key] = (*previous[:3], previous[3] + 1)

    for (facility, bucket), (actual, day, residents, days) in sorted(worst.items()):
        yield Finding(
            "HPRD_BELOW_MINIMUM",
            {
                "facility": context.facility_name(facility),
                "work_date": day,
                "bucket": bucket,
                "actual": actual,
                "minimum": minimums[bucket],
                "residents": residents,
                "days": days,
            },
            key_parts=(facility, bucket),
        )


@evaluator("CNA_RECERT_EVIDENCE_INSUFFICIENT")
def aide_recertification(context: RuleContext) -> Iterable[Finding]:
    """Whether the payroll we hold can support an aide's renewal.

    Deliberately worded as evidence we can see rather than as a fact: the hours may
    well exist in a payroll export nobody sent us, and saying otherwise would accuse
    a facility of something on the strength of a partial file.
    """
    recert = context.setting("cna_recert", {}) or {}
    required = float(recert.get("min_paid_hours", 0) or 0)
    months = int(recert.get("period_months", 24) or 24)
    if required <= 0:
        return

    aides = _aide_roles(context)
    for credential in context.credentials:
        if (credential.credential_type or "").upper() != "CNA" or not credential.holder_id:
            continue
        if credential.expires_on is None:
            continue
        window_start = credential.expires_on - timedelta(days=int(months * 30.44))
        found = sum_hours(
            line.hours_paid
            for line in context.pay_lines
            if line.person_id == credential.holder_id
            and line.role_code.upper() in aides
            and line.period_end
            and window_start <= line.period_end <= credential.expires_on
        )
        if found >= required:
            continue
        yield Finding(
            "CNA_RECERT_EVIDENCE_INSUFFICIENT",
            {
                "display_name": context.display_name(credential.holder_id),
                "found_hours": found,
                "required_hours": required,
                "window_months": months,
                "expires_on": credential.expires_on,
            },
            entities=(context.entity(credential.holder_id),),
            key_parts=(credential.credential_id,),
        )
