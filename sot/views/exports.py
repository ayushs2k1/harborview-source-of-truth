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


def write_run_reports(result: Any, out_dir: Path) -> list[Path]:
    """Write every report for a run. Returns the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    flags = result.flags
    written = [
        out_dir / "flags.csv",
        out_dir / "flags.json",
        out_dir / "summary.md",
    ]
    write_flags_csv(written[0], flags)
    write_flags_json(written[1], flags)
    write_summary_md(written[2], result)
    return written


def load_flags_json(path: Path) -> list[dict[str, Any]]:
    """Read back a flags.json, for tests and for run-to-run comparison."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
