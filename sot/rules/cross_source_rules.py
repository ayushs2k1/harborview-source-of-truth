"""Rules that need more than one source to see.

This is the point of the system. Any one of these files looks fine on its own; the
findings live in the gaps between them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from sot.canon import round_hours
from sot.match.fourway import (
    STATUS_HOURS_VARIANCE,
    STATUS_PAID_NOT_SCHEDULED,
    STATUS_SCHEDULED_NOT_PAID,
)
from sot.rules.engine import RuleContext, evaluator
from sot.rules.model import Finding
from sot.tri import Tri


@evaluator("COVERAGE_GAP_BETWEEN_SOURCES")
def coverage_gap(context: RuleContext) -> Iterable[Finding]:
    """Sources covering different periods: one finding, not one per person.

    Without this, a payroll export three weeks longer than the rota reports every
    nurse as having been paid for weeks they did not work - which is true of the data
    and useless as a finding.
    """
    coverage = context.match.coverage
    if coverage.schedule is None or coverage.payroll is None:
        return
    if not context.match.uncovered:
        return
    yield Finding(
        "COVERAGE_GAP_BETWEEN_SOURCES",
        {
            "schedule_range": f"{coverage.schedule.start} to {coverage.schedule.end}",
            "payroll_range": f"{coverage.payroll.start} to {coverage.payroll.end}",
            "excluded": len(context.match.uncovered),
        },
        key_parts=("coverage",),
    )


@evaluator("PAID_NOT_SCHEDULED", "SCHEDULED_NOT_PAID", "HOURS_VARIANCE")
def week_statuses(context: RuleContext) -> Iterable[Finding]:
    """Turn each person-week's primary status into a finding."""
    for week in context.match.weeks:
        if not week.in_both_coverages:
            continue
        display = context.display_name(week.person_id)
        shared = {
            "display_name": display,
            "facility": week.facility_code or "an unrecorded site",
            "period_start": week.period.start,
            "period_end": week.period.end,
            "paid_hours": week.paid_hours,
            "scheduled_hours": week.scheduled_work_hours,
        }
        key = (week.person_id, week.period.start.isoformat(), week.facility_code)

        if week.status == STATUS_PAID_NOT_SCHEDULED:
            yield Finding(
                "PAID_NOT_SCHEDULED",
                shared,
                entities=(context.entity(week.person_id),),
                key_parts=key,
            )
        elif week.status == STATUS_SCHEDULED_NOT_PAID:
            yield Finding(
                "SCHEDULED_NOT_PAID",
                shared,
                entities=(context.entity(week.person_id),),
                key_parts=key,
            )
        elif week.status == STATUS_HOURS_VARIANCE:
            explanation = (
                f"The difference matches {week.scheduled_pto_hours} hours of paid leave "
                "on the rota."
                if week.explained_by_pto
                else "Nothing on the rota accounts for the difference."
            )
            yield Finding(
                "HOURS_VARIANCE",
                {
                    **shared,
                    "delta": week.delta,
                    "direction": week.direction,
                    "explained_by_pto": week.explained_by_pto,
                    "explanation": explanation,
                },
                entities=(context.entity(week.person_id),),
                key_parts=key,
            )


@evaluator("PAYROLL_PERIOD_INVALID")
def payroll_period_invalid(context: RuleContext) -> Iterable[Finding]:
    """A pay period that is not the shape the pack expects."""
    week_start = str(context.setting("week_start", "monday")).lower()
    expected_index = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }.get(week_start, 0)

    seen: set[tuple[str, str]] = set()
    for line in context.pay_lines:
        start, end = line.period_start, line.period_end
        if start is None or end is None:
            continue
        problems: list[str] = []
        if end < start:
            problems.append("it ends before it starts")
        elif (end - start).days + 1 != 7:
            problems.append(f"it covers {(end - start).days + 1} days rather than 7")
        if start.weekday() != expected_index:
            problems.append(f"it starts on a {start:%A} rather than a {week_start.title()}")
        if not problems:
            continue
        marker = (start.isoformat(), end.isoformat())
        if marker in seen:
            continue
        seen.add(marker)
        yield Finding(
            "PAYROLL_PERIOD_INVALID",
            {
                "record_label": line.payroll_ref or line.pay_line_id,
                "period_start": start,
                "period_end": end,
                "problem": " and ".join(problems),
            },
            entities=(context.entity(line.person_id),) if line.person_id else (),
            row_index=line.row_index,
            key_parts=("period", *marker),
        )


@evaluator("OVERLAPPING_SHIFTS")
def overlapping_shifts(context: RuleContext) -> Iterable[Finding]:
    """The same person in two places at once."""
    by_person: dict[str, list[dict]] = {}
    for segment in context.segments:
        person_id = str(segment.get("person_id") or "")
        if not person_id or segment.get("start_ts") is None or segment.get("end_ts") is None:
            continue
        by_person.setdefault(person_id, []).append(dict(segment))

    for person_id, spans in sorted(by_person.items()):
        spans.sort(key=lambda item: (item["start_ts"], item["end_ts"], item["segment_id"]))
        for index in range(len(spans) - 1):
            first, second = spans[index], spans[index + 1]
            if second["start_ts"] >= first["end_ts"]:
                continue
            yield Finding(
                "OVERLAPPING_SHIFTS",
                {
                    "display_name": context.display_name(person_id),
                    "work_date": first["start_ts"].date(),
                    "first_facility": first.get("facility_code") or "an unrecorded site",
                    "first_window": f"{first['start_ts']:%H:%M} to {first['end_ts']:%H:%M}",
                    "second_facility": second.get("facility_code") or "an unrecorded site",
                    "second_window": f"{second['start_ts']:%H:%M} to {second['end_ts']:%H:%M}",
                },
                entities=(context.entity(person_id),),
                page=first.get("page"),
                key_parts=(person_id, str(first["start_ts"].date()), first["segment_id"]),
            )


@evaluator("LICENSED_ROLE_NO_CREDENTIAL", "ROLE_EXCEEDS_LICENSE")
def scope_of_practice(context: RuleContext) -> Iterable[Finding]:
    """Working a role the person's credentials do not support.

    Two shapes. Nothing on file at all, and something on file that does not reach.
    Both are the same question - may this person do this work - and both change which
    staffing category the hours are reported under.
    """
    roles_by_person: dict[str, dict[str, set[str]]] = {}

    def note(person_id: str, role: str, where: str) -> None:
        if person_id and role:
            roles_by_person.setdefault(person_id, {}).setdefault(role.upper(), set()).add(where)

    for day in context.match.days:
        if day.work_hours > 0:
            note(day.person_id, day.role_code, "the rota")
    for line in context.pay_lines:
        if line.hours_paid > 0:
            note(line.person_id, line.role_code, "payroll")
    for person in context.persons:
        note(getattr(person, "person_id", ""), getattr(person, "role_code", "") or "", "the roster")

    for person_id, roles in sorted(roles_by_person.items()):
        held = {
            (credential.credential_type or "").upper()
            for credential in context.credentials_for(person_id)
        }
        held.discard("")
        for role, sources in sorted(roles.items()):
            accepted = context.role_requires_credential(role)
            if not accepted:
                continue
            if held & set(accepted):
                continue
            display = context.display_name(person_id)
            facility = _facility_for(context, person_id)
            if not held:
                yield Finding(
                    "LICENSED_ROLE_NO_CREDENTIAL",
                    {
                        "display_name": display,
                        "role": role,
                        "facility": facility,
                        "required": " or ".join(accepted),
                    },
                    entities=(context.entity(person_id),),
                    key_parts=(person_id, role),
                )
            else:
                yield Finding(
                    "ROLE_EXCEEDS_LICENSE",
                    {
                        "display_name": display,
                        "claimed_role": role,
                        "source_label": " and ".join(sorted(sources)),
                        "held_credentials": ", ".join(sorted(held)),
                        "required": " or ".join(accepted),
                    },
                    entities=(context.entity(person_id),),
                    key_parts=(person_id, role),
                )


def _facility_for(context: RuleContext, person_id: str) -> str:
    person = context.person(person_id)
    return (
        getattr(person, "facility_code", None)
        or context.golden.person(person_id, "home_facility")
        or "an unrecorded site"
    )


@evaluator("HOURS_EXCESSIVE_WEEK")
def excessive_weekly_hours(context: RuleContext) -> Iterable[Finding]:
    """More hours in a week than a week has, or than a person plausibly works."""
    totals: dict[tuple[str, str], float] = {}
    for line in context.pay_lines:
        if not line.person_id or not line.period_start:
            continue
        key = (line.person_id, line.period_start.isoformat())
        totals[key] = round_hours(totals.get(key, 0.0) + line.hours_paid) or 0.0

    for (person_id, period_start), hours in sorted(totals.items()):
        if hours <= 80:
            continue
        note = (
            "A week is 168 hours long, so this cannot be right."
            if hours > 168
            else "That is more than 80 hours in one week."
        )
        yield Finding(
            "HOURS_EXCESSIVE_WEEK",
            {
                "display_name": context.display_name(person_id),
                "hours": hours,
                "period_start": period_start,
                "note": note,
            },
            entities=(context.entity(person_id),),
            key_parts=(person_id, period_start),
        )


@evaluator("PBJ_UNALLOCATED_HOURS")
def unallocated_hours(context: RuleContext) -> Iterable[Finding]:
    """Paid hours with no rota day. Never given one."""
    for item in getattr(context.daily_hours, "unallocated", ()) or ():
        yield Finding(
            "PBJ_UNALLOCATED_HOURS",
            {
                "display_name": item.display_name,
                "hours": item.hours,
                "facility": item.facility_code or "an unrecorded site",
                "period_start": item.period_start,
                "period_end": item.period_end,
            },
            entities=(context.entity(item.person_id),),
            key_parts=(item.person_id, item.period_start.isoformat(), item.facility_code),
        )


@evaluator("ACTIVITY_BEFORE_HIRE")
def activity_before_hire(context: RuleContext) -> Iterable[Finding]:
    """Paid or rostered before the start date on file."""
    for person in context.persons:
        person_id = getattr(person, "person_id", "")
        hire = context.golden.person_date(person_id, "hire_date")
        if hire is None:
            continue
        earliest: tuple[str, object] | None = None
        for day in context.match.days:
            if day.person_id != person_id or day.work_date >= hire:
                continue
            if earliest is None or day.work_date < earliest[1]:
                earliest = ("shifts on the rota", day.work_date)
        for line in context.pay_lines:
            if line.person_id != person_id or not line.period_start or line.period_end >= hire:
                continue
            if earliest is None or line.period_start < earliest[1]:
                earliest = ("paid hours", line.period_start)
        if earliest is None:
            continue
        yield Finding(
            "ACTIVITY_BEFORE_HIRE",
            {
                "display_name": context.display_name(person_id),
                "hire_date": hire,
                "activity": earliest[0],
                "activity_date": earliest[1],
            },
            entities=(context.entity(person_id),),
            key_parts=(person_id,),
        )


@evaluator("HIRE_DATE_IN_FUTURE")
def hire_date_in_future(context: RuleContext) -> Iterable[Finding]:
    for person in context.persons:
        person_id = getattr(person, "person_id", "")
        hire = context.golden.person_date(person_id, "hire_date")
        if hire is None or hire <= context.as_of:
            continue
        yield Finding(
            "HIRE_DATE_IN_FUTURE",
            {
                "display_name": context.display_name(person_id),
                "hire_date": hire,
                "as_of": context.as_of,
            },
            entities=(context.entity(person_id),),
            key_parts=(person_id,),
        )


@evaluator("DAILY_HOURS_OVER_CAP", "LONG_DAY")
def long_days(context: RuleContext) -> Iterable[Finding]:
    """More hours in one day than reporting allows, or than is safe."""
    cap = float(context.setting("pbj.daily_cap_hours", 22.5) or 22.5)
    fatigue = float(context.setting("fatigue.long_day_hours", 16) or 16)

    totals: dict[tuple[str, object], float] = {}
    for day in context.match.days:
        key = (day.person_id, day.work_date)
        totals[key] = round_hours(totals.get(key, 0.0) + day.work_hours) or 0.0

    for (person_id, work_date), hours in sorted(totals.items(), key=lambda item: str(item[0])):
        if hours > cap:
            yield Finding(
                "DAILY_HOURS_OVER_CAP",
                {
                    "display_name": context.display_name(person_id),
                    "hours": hours,
                    "work_date": work_date,
                    "cap": cap,
                },
                entities=(context.entity(person_id),),
                key_parts=(person_id, str(work_date)),
            )
        elif hours > fatigue:
            yield Finding(
                "LONG_DAY",
                {
                    "display_name": context.display_name(person_id),
                    "hours": hours,
                    "work_date": work_date,
                    "limit": fatigue,
                },
                entities=(context.entity(person_id),),
                key_parts=(person_id, str(work_date)),
            )


@evaluator("SHORT_REST", "CONSECUTIVE_DAYS")
def fatigue_patterns(context: RuleContext) -> Iterable[Finding]:
    """Patterns across days rather than within one."""
    min_rest = float(context.setting("fatigue.min_rest_hours", 8) or 8)
    max_run = int(context.setting("fatigue.max_consecutive_days", 7) or 7)

    by_person: dict[str, list[dict]] = {}
    for segment in context.segments:
        person_id = str(segment.get("person_id") or "")
        if not person_id or segment.get("start_ts") is None or segment.get("end_ts") is None:
            continue
        if str(segment.get("category") or "") not in {"WORK", "TRAINING"}:
            continue
        by_person.setdefault(person_id, []).append(dict(segment))

    for person_id, spans in sorted(by_person.items()):
        spans.sort(key=lambda item: (item["start_ts"], item["segment_id"]))
        for index in range(len(spans) - 1):
            rest = (spans[index + 1]["start_ts"] - spans[index]["end_ts"]).total_seconds() / 3600
            if 0 <= rest < min_rest:
                yield Finding(
                    "SHORT_REST",
                    {
                        "display_name": context.display_name(person_id),
                        "previous_end": f"{spans[index]['end_ts']:%a %d %b %H:%M}",
                        "next_start": f"{spans[index + 1]['start_ts']:%a %d %b %H:%M}",
                        "rest_hours": round_hours(rest),
                        "min_rest": min_rest,
                    },
                    entities=(context.entity(person_id),),
                    key_parts=(person_id, str(spans[index]["segment_id"])),
                )

        dates = sorted({item["start_ts"].date() for item in spans})
        run_start, run_length = None, 0
        for index, when in enumerate(dates):
            if index and (when - dates[index - 1]) == timedelta(days=1):
                run_length += 1
            else:
                run_start, run_length = when, 1
            if run_length > max_run:
                yield Finding(
                    "CONSECUTIVE_DAYS",
                    {
                        "display_name": context.display_name(person_id),
                        "days": run_length,
                        "start_date": run_start,
                        "limit": max_run,
                    },
                    entities=(context.entity(person_id),),
                    key_parts=(person_id, str(run_start)),
                )
                break


@evaluator("CNA_HOURS_EXCLUDED_UNCERTIFIED")
def uncertified_aide_hours(context: RuleContext) -> Iterable[Finding]:
    """Aide hours on days with no valid certification do not count towards staffing."""
    aide_roles = {
        role
        for role in (context.setting("required_credential", {}) or {})
        if role.upper() in {"CNA", "AIDE", "MED_AIDE"}
    }
    excluded: dict[tuple[str, str], float] = {}
    for day in context.match.days:
        if day.role_code.upper() not in aide_roles or day.work_hours <= 0:
            continue
        if day.credential_valid is Tri.PASS:
            continue
        key = (day.person_id, day.facility_code)
        excluded[key] = round_hours(excluded.get(key, 0.0) + day.work_hours) or 0.0

    for (person_id, facility), hours in sorted(excluded.items()):
        yield Finding(
            "CNA_HOURS_EXCLUDED_UNCERTIFIED",
            {
                "display_name": context.display_name(person_id),
                "hours": hours,
                "facility": facility or "an unrecorded site",
            },
            entities=(context.entity(person_id),),
            key_parts=(person_id, facility),
        )


@evaluator("FACILITY_CONFLICT")
def facility_conflict(context: RuleContext) -> Iterable[Finding]:
    """Hours paid at a site the person was not rostered at.

    Compared per person per period rather than by picking one facility per person.
    Somebody who legitimately works at two sites has two facilities in every source,
    and a comparison that collapsed them to one value each would report every float
    as a conflict - which is the opposite of useful, since floats are exactly the
    people whose hours are hardest to attribute.
    """
    paid: dict[tuple[str, object], set[str]] = {}
    worked: dict[tuple[str, object], set[str]] = {}

    for week in context.match.weeks:
        if not week.in_both_coverages or not week.facility_code:
            continue
        key = (week.person_id, week.period.start)
        if week.paid_hours > 0:
            paid.setdefault(key, set()).add(week.facility_code)
        if week.scheduled_work_hours > 0:
            worked.setdefault(key, set()).add(week.facility_code)

    for key in sorted(set(paid) & set(worked), key=lambda item: (item[0], str(item[1]))):
        person_id, period_start = key
        paid_sites, worked_sites = paid[key], worked[key]
        if paid_sites == worked_sites:
            continue
        yield Finding(
            "FACILITY_CONFLICT",
            {
                "display_name": context.display_name(person_id),
                "values": (
                    f"{', '.join(sorted(paid_sites))} in payroll and "
                    f"{', '.join(sorted(worked_sites))} on the schedule for the week of "
                    f"{period_start}"
                ),
            },
            entities=(context.entity(person_id),),
            key_parts=(person_id, str(period_start), "facility"),
        )


@evaluator("ROLE_CONFLICT")
def role_conflict(context: RuleContext) -> Iterable[Finding]:
    """Systems disagreeing about what somebody does.

    It changes which staffing category their hours are reported under, which is why a
    nurse paid under an aide code matters even when the hours themselves reconcile.
    """
    for person in context.persons:
        person_id = getattr(person, "person_id", "")
        if not person_id:
            continue
        seen: dict[str, set[str]] = {}
        roster_role = (context.golden.person(person_id, "job_title") or "").upper()
        if roster_role:
            seen.setdefault(roster_role, set()).add("the roster")
        for line in context.pay_lines:
            if line.person_id == person_id and line.role_code:
                seen.setdefault(line.role_code.upper(), set()).add("payroll")
        for day in context.match.days:
            if day.person_id == person_id and day.role_code and day.work_hours > 0:
                seen.setdefault(day.role_code.upper(), set()).add("the schedule")
        if len(seen) < 2:
            continue
        yield Finding(
            "ROLE_CONFLICT",
            {
                "display_name": context.display_name(person_id),
                "values": ", ".join(
                    f"{role} in {' and '.join(sorted(sources))}"
                    for role, sources in sorted(seen.items())
                ),
            },
            entities=(context.entity(person_id),),
            key_parts=(person_id, "role"),
        )
