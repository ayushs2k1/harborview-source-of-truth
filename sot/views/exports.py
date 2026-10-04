"""Writing a run's results to disk.

The CLI path exists so the system can be demonstrated, audited, and re-run without a
browser. Everything the UI shows should also be obtainable as a file.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sot.canon import canonical_json
from sot.rules.model import Flag, Severity

FLAG_COLUMNS = (
    "flag_id",
    "rule_code",
    "severity",
    "category",
    "title",
    "message",
    "entities",
    "suggested_action",
    "owner_role",
    "occurrence_count",
    "evidence",
)


def _entities(flag: Flag) -> str:
    return "; ".join(entity.display or entity.id for entity in flag.entities)


def _evidence(flag: Flag) -> str:
    parts = []
    for item in flag.evidence:
        bits = [
            item.source_type or "",
            f"row {item.row_index}" if item.row_index else "",
            f"page {item.page}" if item.page else "",
            item.column_name or "",
        ]
        parts.append(" ".join(bit for bit in bits if bit))
    return "; ".join(part for part in parts if part)


def write_flags_csv(path: Path, flags: list[Flag]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(FLAG_COLUMNS)
        for flag in flags:
            writer.writerow(
                [
                    flag.flag_id,
                    flag.rule_code,
                    str(flag.severity),
                    str(flag.category),
                    flag.title,
                    flag.message,
                    _entities(flag),
                    flag.suggested_action,
                    str(flag.owner_role),
                    flag.occurrence_count,
                    _evidence(flag),
                ]
            )


def write_flags_json(path: Path, flags: list[Flag]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "flag_id": flag.flag_id,
            "rule_code": flag.rule_code,
            "severity": str(flag.severity),
            "category": str(flag.category),
            "title": flag.title,
            "message": flag.message,
            "suggested_action": flag.suggested_action,
            "owner_role": str(flag.owner_role),
            "occurrence_count": flag.occurrence_count,
            "entities": [entity.as_dict() for entity in flag.entities],
            "evidence": [
                {
                    "file_id": item.file_id,
                    "source_type": item.source_type,
                    "row": item.row_index,
                    "page": item.page,
                    "column": item.column_name,
                    "raw_value": item.raw_value,
                    "bbox": list(item.bbox) if item.bbox else None,
                }
                for item in flag.evidence
            ],
            "params": flag.params,
        }
        for flag in flags
    ]
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def write_summary_md(path: Path, result: Any) -> None:
    """A short, readable account of what happened, for a human or a commit message."""
    flags = result.flags
    counts = Counter(str(flag.severity) for flag in flags)
    by_code = Counter(flag.rule_code for flag in flags)

    lines = [
        f"# Run {result.run_id}",
        "",
        f"- **Pack**: {result.pack}",
        f"- **As of**: {result.as_of}",
        f"- **Status**: {result.status}",
        f"- **Files**: {len(result.files)}",
        f"- **Records**: {result.record_count:,}",
        f"- **Quarantined rows**: {result.quarantined_count:,}",
        "",
        "## Findings",
        "",
    ]
    if not flags:
        lines.append("Nothing to report. Every check passed.")
    else:
        lines.append("| Severity | Count |")
        lines.append("|---|---|")
        for severity in Severity:
            lines.append(f"| {severity.value} | {counts.get(severity.value, 0)} |")
        lines.extend(["", "| Rule | Count |", "|---|---|"])
        for code, count in sorted(by_code.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| `{code}` | {count} |")

    lines.extend(["", "## Files", "", "| File | Type | Confidence | Rows |", "|---|---|---|---|"])
    reads = {read.landed.file_id: read for read in result.reads}
    for item in result.files:
        read = reads.get(item.file_id)
        source = read.detection.source if read else ("duplicate" if item.is_duplicate else "-")
        score = f"{read.detection.score:.0%}" if read else "-"
        rows = f"{len(read.records):,}" if read else "-"
        lines.append(f"| {item.original_name} | {source or 'unknown'} | {score} | {rows} |")

    summaries = getattr(result, "summaries", None) or []
    if summaries:
        lines.extend(
            [
                "",
                "## Staffing",
                "",
                "| Facility | Period | Reported hours | Verified | Unallocated | Zero-RN days | Variance |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for item in summaries:
            lines.append(
                f"| {item.facility_name} | {item.period_start} to {item.period_end} "
                f"| {item.total_hours:g} | {item.pct_verified}% | {item.unallocated_hours:g} "
                f"| {item.zero_rn_days} | {item.traceability_variance_pct}% |"
            )
        if summaries[0].quarter:
            lines.extend(["", f"Filing period: **{summaries[0].quarter.description}**."])

    expirations = getattr(result, "expirations", None)
    if expirations is not None and expirations.needs_attention:
        lines.extend(
            [
                "",
                "## Expiring",
                "",
                "| Holder | Type | Expires | Days left | Band | Worked after expiry |",
                "|---|---|---|---|---|---|",
            ]
        )
        for row in expirations.needs_attention[:20]:
            lines.append(
                f"| {row.holder} | {row.credential_type} | {row.expires_on or '-'} "
                f"| {'-' if row.days_left is None else row.days_left} | {row.band} "
                f"| {row.shifts_worked_after_expiry} |"
            )

    if flags:
        lines.extend(["", "## Detail", ""])
        for flag in flags:
            lines.append(f"### {flag.severity.value} · {flag.rule_code}")
            lines.append("")
            lines.append(flag.message)
            lines.append("")
            lines.append(f"*{flag.suggested_action}* — owner: {flag.owner_role.value}")
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_referrals(result: Any, pack: Any) -> list[Any]:
    """Assess every facility-day the rota covers.

    Produced for the report rather than on demand so the CLI output answers the
    admissions question without anybody opening a browser.
    """
    from datetime import timedelta

    from sot.views.referral import assess_referral

    if result.match is None or result.match.coverage.schedule is None:
        return []
    coverage = result.match.coverage.schedule
    # The resolved copies: the adapter's own segments have no person attached,
    # because identity resolution had not run when they were made.
    segments = list(getattr(result, "segments", ()) or [])
    if not segments:
        return []
    facilities = sorted(
        {
            str(segment.get("facility_code") or "")
            for segment in segments
            if segment.get("facility_code")
        }
    )
    display_names = (
        {person.person_id: person.display_name for person in result.resolution.persons}
        if result.resolution
        else {}
    )
    census = _census_map(result)
    flags = [
        {"rule_code": flag.rule_code, "message": flag.message, "severity": str(flag.severity)}
        for flag in result.flags
    ]

    assessments = []
    for facility in facilities:
        day = coverage.start
        while day <= coverage.end:
            assessments.append(
                assess_referral(
                    facility_code=facility,
                    work_date=day,
                    pack=pack,
                    segments=segments,
                    person_days=result.match.days,
                    daily_rows=result.staffing.rows if result.staffing else [],
                    flags=flags,
                    display_names=display_names,
                    census=census.get((facility, day)),
                    coverage=coverage,
                )
            )
            day += timedelta(days=1)
    return assessments


def _census_map(result: Any) -> dict[tuple[str, Any], int]:
    import json
    from datetime import date as date_type

    census: dict[tuple[str, Any], int] = {}
    for read in getattr(result, "reads", []):
        if read.detection.role != "census":
            continue
        for record in read.records:
            payload = json.loads(record["payload_json"])
            facility = str(payload.get("facility") or payload.get("facility_code") or "")
            try:
                when = date_type.fromisoformat(str(payload.get("date") or ""))
                census[(facility, when)] = int(float(payload.get("residents")))
            except (TypeError, ValueError):
                continue
    return census


def write_run_reports(result: Any, out_dir: Path, pack: Any = None) -> list[Path]:
    """Write every report for a run. Returns the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    flags = result.flags

    written = [out_dir / "flags.csv", out_dir / "flags.json"]
    write_flags_csv(written[0], flags)
    write_flags_json(written[1], flags)

    if getattr(result, "staffing", None) is not None:
        path = out_dir / "pbj_daily_hours.csv"
        write_daily_hours_csv(path, result.staffing)
        written.append(path)
    if getattr(result, "summaries", None):
        path = out_dir / "staffing_summary.csv"
        write_staffing_summary_csv(path, result.summaries)
        written.append(path)
    if getattr(result, "expirations", None) is not None:
        path = out_dir / "expirations.csv"
        write_expirations_csv(path, result.expirations)
        written.append(path)
    if pack is not None:
        referrals = build_referrals(result, pack)
        if referrals:
            path = out_dir / "referral_readiness.csv"
            write_referral_csv(path, referrals)
            written.append(path)

    summary = out_dir / "summary.md"
    write_summary_md(summary, result)
    written.append(summary)
    return written


def load_flags_json(path: Path) -> list[dict[str, Any]]:
    """Read back a flags.json, for tests and for run-to-run comparison."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# View exports
# ---------------------------------------------------------------------------


def _write_rows(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_daily_hours_csv(path: Path, staffing: Any) -> None:
    """Reportable hours by day, person and site, with the tier on every figure."""
    _write_rows(
        path,
        [
            "facility",
            "work_date",
            "person_id",
            "display_name",
            "role",
            "pbj_job_code",
            "scheduled_hours",
            "meal_deduction",
            "pbj_hours",
            "tier",
        ],
        [
            [
                row.facility_code,
                row.work_date.isoformat(),
                row.person_id,
                row.display_name,
                row.role_code,
                row.pbj_job_code,
                f"{row.scheduled_hours:g}",
                f"{row.meal_deduction:g}",
                f"{row.pbj_hours:g}",
                row.tier,
            ]
            for row in (staffing.rows if staffing else [])
        ],
    )


def write_staffing_summary_csv(path: Path, summaries: list[Any]) -> None:
    """One row per facility per period, in the shape the quarterly filing needs."""
    _write_rows(
        path,
        [
            "facility",
            "period_start",
            "period_end",
            "total_hours",
            "verified_hours",
            "conflict_hours",
            "schedule_only_hours",
            "unallocated_hours",
            "pct_verified",
            "pct_unallocated",
            "zero_rn_days",
            "zero_rn_warn",
            "zero_rn_critical",
            "cap_violations",
            "traceability_variance_pct",
            "traceability_threshold",
            "quarter",
            "quarter_due",
        ],
        [
            [
                item.facility_name,
                item.period_start.isoformat(),
                item.period_end.isoformat(),
                f"{item.total_hours:g}",
                f"{item.verified_hours:g}",
                f"{item.conflict_hours:g}",
                f"{item.schedule_only_hours:g}",
                f"{item.unallocated_hours:g}",
                item.pct_verified,
                item.pct_unallocated,
                item.zero_rn_days,
                item.zero_rn_warn,
                item.zero_rn_critical,
                item.cap_violations,
                item.traceability_variance_pct,
                item.traceability_threshold,
                item.quarter.description if item.quarter else "",
                item.quarter.due.isoformat() if item.quarter else "",
            ]
            for item in summaries
        ],
    )


def write_expirations_csv(path: Path, view: Any) -> None:
    """Everything that expires, most urgent first."""
    _write_rows(
        path,
        [
            "holder_type",
            "holder",
            "type",
            "number",
            "facility",
            "expires_on",
            "days_left",
            "band",
            "last_verified",
            "verified_age_days",
            "verification_stale",
            "next_shift_after_expiry",
            "shifts_worked_after_expiry",
            "recert_hours_found",
            "recert_hours_required",
            "recert_ready",
        ],
        [
            [
                row.holder_type,
                row.holder,
                row.credential_type,
                row.number,
                row.facility,
                row.expires_on.isoformat() if row.expires_on else "",
                "" if row.days_left is None else row.days_left,
                row.band,
                row.last_verified.isoformat() if row.last_verified else "",
                "" if row.verified_age_days is None else row.verified_age_days,
                "yes" if row.verification_stale else "no",
                row.next_shift_after_expiry.isoformat() if row.next_shift_after_expiry else "",
                row.shifts_worked_after_expiry,
                "" if row.recert_hours_found is None else f"{row.recert_hours_found:g}",
                "" if row.recert_hours_required is None else f"{row.recert_hours_required:g}",
                "" if row.recert_ready is None else ("yes" if row.recert_ready else "no"),
            ]
            for row in (view.rows if view else [])
        ],
    )


def write_referral_csv(path: Path, assessments: list[Any]) -> None:
    """One row per facility-day assessed, with the verdict and why."""
    _write_rows(
        path,
        [
            "facility",
            "date",
            "verdict",
            "rn_covered",
            "rn_longest_run",
            "rn_required_hours",
            "licensed_hours",
            "aide_hours",
            "total_hours",
            "census",
            "open_critical",
            "reasons",
        ],
        [
            [
                item.facility_name,
                item.work_date.isoformat(),
                item.verdict,
                str(item.rn_covered),
                f"{item.rn_longest_run:g}",
                f"{item.rn_required_hours:g}",
                f"{item.licensed_hours:g}",
                f"{item.aide_hours:g}",
                f"{item.total_hours:g}",
                "" if item.census is None else item.census,
                len(item.open_critical),
                " | ".join(item.reasons),
            ]
            for item in assessments
        ],
    )
