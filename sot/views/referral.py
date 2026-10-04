"""Referral readiness.

The client's first problem: "hospitals send us patient referrals, and by the time we
get through them, the patient has often gone somewhere else." The delay is not in the
decision, it is in assembling the evidence for it - who is on, are they licensed, is
there a nurse covering the whole day, can we take one more.

This answers that in one call. It is deliberately a *fast admissions indicator* and
says so: the statutory standard is a quarterly average against census, and no
single-day view can stand in for that. What it can do is tell an administrator
whether today is obviously fine, obviously not, or not knowable from what we hold.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sot.canon import round_hours, sum_hours
from sot.rules.domain_healthcare import longest_run
from sot.tri import Tri

VERDICT_YES = "YES"
VERDICT_NO = "NO"
VERDICT_UNKNOWN = "UNKNOWN"


@dataclass
class OnDuty:
    """One person on the rota for the day in question."""

    person_id: str
    display_name: str
    role_code: str
    hours: float
    window: str
    credential_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "display_name": self.display_name,
            "role_code": self.role_code,
            "hours": self.hours,
            "window": self.window,
            "credential_status": self.credential_status,
        }


@dataclass
class ReferralAssessment:
    """Whether this facility can take an admission on this day."""

    facility_code: str
    facility_name: str
    work_date: date
    verdict: str = VERDICT_UNKNOWN
    reasons: list[str] = field(default_factory=list)
    rn_covered: Tri = Tri.UNKNOWN
    rn_longest_run: float = 0.0
    rn_required_hours: float = 0.0
    rn_windows: list[str] = field(default_factory=list)
    licensed_hours: float = 0.0
    aide_hours: float = 0.0
    total_hours: float = 0.0
    tours: dict[str, bool] = field(default_factory=dict)
    on_duty: list[OnDuty] = field(default_factory=list)
    open_critical: list[dict[str, Any]] = field(default_factory=list)
    census: int | None = None
    hprd: dict[str, float] = field(default_factory=dict)
    hprd_plus_one: dict[str, float] = field(default_factory=dict)
    hprd_minimums: dict[str, float] = field(default_factory=dict)
    note: str = (
        "A fast admissions indicator. Statutory staffing is assessed as a quarterly "
        "average against census, which no single day can stand in for."
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "facility_code": self.facility_code,
            "facility": self.facility_name,
            "date": self.work_date.isoformat(),
            "verdict": self.verdict,
            "reasons": self.reasons,
            "rn_covered": str(self.rn_covered),
            "rn_longest_run": self.rn_longest_run,
            "rn_required_hours": self.rn_required_hours,
            "rn_windows": self.rn_windows,
            "licensed_hours": self.licensed_hours,
            "aide_hours": self.aide_hours,
            "total_hours": self.total_hours,
            "tours": self.tours,
            "on_duty": [person.as_dict() for person in self.on_duty],
            "open_critical": self.open_critical,
            "census": self.census,
            "hprd": self.hprd,
            "hprd_plus_one": self.hprd_plus_one,
            "hprd_minimums": self.hprd_minimums,
            "note": self.note,
        }


def _parse_tour(window: str) -> tuple[float, float]:
    start_text, _, end_text = str(window).partition("-")

    def to_hours(text: str) -> float:
        parts = text.strip().split(":")
        return int(parts[0]) + (int(parts[1]) / 60 if len(parts) > 1 else 0)

    start, end = to_hours(start_text), to_hours(end_text)
    return (start, end if end > start else end + 24)


def _intervals(segments: Sequence[Mapping[str, Any]], when: date) -> list[tuple[float, float]]:
    """Hours-from-midnight intervals a set of segments covers on one day."""
    spans: list[tuple[float, float]] = []
    midnight = datetime.combine(when, time.min)
    for segment in segments:
        start, end = segment.get("start_ts"), segment.get("end_ts")
        if start is None or end is None:
            continue
        clipped_start = max(start, midnight)
        clipped_end = min(end, midnight + timedelta(days=1))
        if clipped_end <= clipped_start:
            continue
        spans.append(
            (
                (clipped_start - midnight).total_seconds() / 3600,
                (clipped_end - midnight).total_seconds() / 3600,
            )
        )
    return spans


def assess_referral(
    *,
    facility_code: str,
    work_date: date,
    pack: Any,
    segments: Sequence[Mapping[str, Any]],
    person_days: Sequence[Any] = (),
    daily_rows: Sequence[Any] = (),
    flags: Sequence[Mapping[str, Any]] = (),
    display_names: Mapping[str, str] | None = None,
    census: int | None = None,
    plus_one: bool = False,
    coverage: Any = None,
) -> ReferralAssessment:
    """Can this facility take an admission on this day, and why."""
    display_names = display_names or {}
    families = pack.setting("role_families", {}) or {}
    rn_roles = {str(role).upper() for role in families.get("nurse_rn", ())}
    licensed_roles = rn_roles | {str(role).upper() for role in families.get("nurse_lpn", ())}
    aide_roles = {str(role).upper() for role in families.get("aide", ())}
    required = float(pack.setting("rn_min_consecutive_hours", 8) or 8)
    minimums = {
        name: float(value) for name, value in (pack.setting("hprd_minimums", {}) or {}).items()
    }

    crosswalk = pack.crosswalk("facilities")
    entry = crosswalk.by_code().get(facility_code) if crosswalk else None
    assessment = ReferralAssessment(
        facility_code=facility_code,
        facility_name=(entry.name if entry and entry.name else facility_code),
        work_date=work_date,
        rn_required_hours=required,
        hprd_minimums=minimums,
        census=census,
    )

    day_segments = [
        segment
        for segment in segments
        if str(segment.get("facility_code") or "") == facility_code
        and str(segment.get("category") or "") in {"WORK", "TRAINING"}
        and _touches(segment, work_date)
    ]

    if coverage is not None and not (coverage.start <= work_date <= coverage.end):
        assessment.verdict = VERDICT_UNKNOWN
        assessment.reasons.append(
            f"The rota we hold covers {coverage.start} to {coverage.end}, "
            f"so there is no record of {work_date}."
        )
        return assessment

    if not day_segments:
        assessment.verdict = VERDICT_UNKNOWN
        assessment.reasons.append("Nobody is on the rota for this day at this site.")
        return assessment

    rn_segments = [
        segment
        for segment in day_segments
        if str(segment.get("role_code") or "").upper() in rn_roles
    ]
    rn_spans = _intervals(rn_segments, work_date)
    assessment.rn_longest_run = longest_run(rn_spans)
    assessment.rn_covered = Tri.PASS if assessment.rn_longest_run >= required else Tri.FAIL
    assessment.rn_windows = [
        f"{display_names.get(str(segment.get('person_id')), '')} "
        f"{segment['start_ts']:%H:%M}-{segment['end_ts']:%H:%M}".strip()
        for segment in sorted(rn_segments, key=lambda item: item["start_ts"])
        if segment.get("start_ts") and segment.get("end_ts")
    ]

    relevant_rows = [
        row
        for row in daily_rows
        if row.facility_code == facility_code and row.work_date == work_date
    ]
    assessment.total_hours = sum_hours(row.pbj_hours for row in relevant_rows)
    assessment.licensed_hours = sum_hours(
        row.pbj_hours for row in relevant_rows if row.role_code.upper() in licensed_roles
    )
    assessment.aide_hours = sum_hours(
        row.pbj_hours for row in relevant_rows if row.role_code.upper() in aide_roles
    )

    for name, window in sorted((pack.setting("tours", {}) or {}).items()):
        start, end = _parse_tour(window)
        licensed_spans = _intervals(
            [
                segment
                for segment in day_segments
                if str(segment.get("role_code") or "").upper() in licensed_roles
            ],
            work_date,
        )
        assessment.tours[name] = any(
            span_start < end and start < span_end for span_start, span_end in licensed_spans
        )

    valid_by_person = {
        day.person_id: str(day.credential_valid)
        for day in person_days
        if day.work_date == work_date and day.facility_code == facility_code
    }
    seen: dict[str, OnDuty] = {}
    for segment in sorted(day_segments, key=lambda item: str(item.get("person_id") or "")):
        person_id = str(segment.get("person_id") or "")
        hours = float(segment.get("hours") or 0)
        window = (
            f"{segment['start_ts']:%H:%M}-{segment['end_ts']:%H:%M}"
            if segment.get("start_ts") and segment.get("end_ts")
            else ""
        )
        if person_id in seen:
            seen[person_id].hours = round_hours(seen[person_id].hours + hours) or 0.0
            continue
        seen[person_id] = OnDuty(
            person_id=person_id,
            display_name=display_names.get(person_id, segment.get("person_ref") or person_id),
            role_code=str(segment.get("role_code") or ""),
            hours=round_hours(hours) or 0.0,
            window=window,
            credential_status=valid_by_person.get(person_id, "UNKNOWN"),
        )
    assessment.on_duty = sorted(seen.values(), key=lambda person: person.display_name)

    assessment.open_critical = [
        {
            "rule_code": flag.get("rule_code"),
            "message": flag.get("message"),
            "severity": flag.get("severity"),
        }
        for flag in flags
        if flag.get("severity") == "CRITICAL"
        and _flag_touches(flag, facility_code, assessment.facility_name, work_date)
    ]

    if census:
        assessment.hprd = _hprd(assessment, census)
        if plus_one:
            assessment.hprd_plus_one = _hprd(assessment, census + 1)

    _decide(assessment, minimums, plus_one)
    return assessment


def _touches(segment: Mapping[str, Any], when: date) -> bool:
    start, end = segment.get("start_ts"), segment.get("end_ts")
    if start is None or end is None:
        work_date = segment.get("work_date")
        return getattr(work_date, "date", lambda: work_date)() == when or work_date == when
    return start.date() <= when <= end.date()


def _flag_touches(
    flag: Mapping[str, Any], facility_code: str, facility_name: str, when: date
) -> bool:
    """Whether an open finding is about this facility on this day.

    Matched on the message rather than on structured fields because a finding may be
    about a facility-day without being about any one person, and the facility-day is
    what the message names.
    """
    message = str(flag.get("message") or "")
    mentions_site = facility_code in message or facility_name in message
    mentions_day = f"{when:%b} {when.day}, {when.year}" in message or when.isoformat() in message
    return mentions_site and mentions_day


def _hprd(assessment: ReferralAssessment, census: int) -> dict[str, float]:
    return {
        "total": round_hours(assessment.total_hours / census) or 0.0,
        "licensed": round_hours(assessment.licensed_hours / census) or 0.0,
        "cna": round_hours(assessment.aide_hours / census) or 0.0,
    }


def _decide(assessment: ReferralAssessment, minimums: Mapping[str, float], plus_one: bool) -> None:
    """Turn the measurements into an answer, with the reasoning attached."""
    blocking: list[str] = []
    notes: list[str] = []

    if assessment.rn_covered is Tri.FAIL:
        blocking.append(
            f"No RN covers {assessment.rn_required_hours:g} consecutive hours "
            f"(the longest unbroken stretch is {assessment.rn_longest_run:g})."
        )
    else:
        notes.append(f"An RN is on duty for {assessment.rn_longest_run:g} consecutive hours.")

    if assessment.open_critical:
        blocking.append(f"{len(assessment.open_critical)} open critical finding(s) touch this day.")

    uncovered_tours = [name for name, covered in sorted(assessment.tours.items()) if not covered]
    if uncovered_tours:
        notes.append(f"No licensed nurse on the {', '.join(uncovered_tours)} tour.")

    target = assessment.hprd_plus_one if plus_one and assessment.hprd_plus_one else assessment.hprd
    if target and minimums:
        short = [
            f"{bucket} would be {target[bucket]:.2f} against a {minimum} minimum"
            for bucket, minimum in sorted(minimums.items())
            if target.get(bucket, 0.0) < minimum
        ]
        if short:
            blocking.append(
                ("With one more resident, " if plus_one else "") + "; ".join(short) + "."
            )
        else:
            notes.append(
                ("With one more resident, " if plus_one else "")
                + "every hours-per-resident minimum is still met."
            )
    elif not assessment.census:
        notes.append("No census was supplied, so hours per resident cannot be checked.")

    unknown_credentials = [
        person.display_name
        for person in assessment.on_duty
        if person.credential_status == "UNKNOWN"
    ]
    if unknown_credentials:
        notes.append(f"Credential status is unknown for {', '.join(unknown_credentials[:3])}.")

    assessment.verdict = VERDICT_NO if blocking else VERDICT_YES
    assessment.reasons = blocking + notes
