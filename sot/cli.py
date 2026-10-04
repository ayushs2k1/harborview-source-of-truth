"""Command line interface.

Exit codes follow spec section 19: bad data is a finding, not a failure, so a run over
hopeless input still exits 0 with flags written. A non-zero exit means the engine
itself broke, which should never happen.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sot.config import ENGINE_VERSION, settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m sot",
        description="Harborview Source of Truth - every number has receipts.",
    )
    parser.add_argument("--version", action="version", version=f"sot {ENGINE_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="ingest a directory of files and write a report")
    ingest.add_argument("path", help="directory (or single file) to ingest")
    ingest.add_argument(
        "--as-of", dest="as_of", help="compliance date, YYYY-MM-DD (default: today)"
    )
    ingest.add_argument("--pack", default=None, help="domain pack id")
    ingest.add_argument(
        "--type",
        dest="type_overrides",
        action="append",
        default=[],
        metavar="FILE=SOURCE",
        help="force a file's source type, e.g. --type payroll.csv=payroll",
    )
    ingest.add_argument("--out", default=None, help="report directory (default: reports/<run_id>)")
    ingest.add_argument(
        "--max-severity",
        dest="max_severity",
        choices=["BLOCKER", "CRITICAL", "WARNING", "INFO"],
        default=None,
        help="exit non-zero if anything worse than this is found (for gates, not daily use)",
    )

    sub.add_parser("health", help="print engine and database status")
    return parser


def _cmd_health() -> int:
    from sot.api.routers.health import health as health_payload

    print(json.dumps(health_payload(), indent=2))
    return 0


def _parse_overrides(raw: list[str]) -> dict[str, str]:
    """Turn ``--type payroll.csv=payroll`` arguments into a mapping."""
    overrides: dict[str, str] = {}
    for item in raw:
        name, _, source = item.partition("=")
        if not name or not source:
            raise SystemExit(f"--type expects FILE=SOURCE, got {item!r}")
        overrides[name.strip()] = source.strip()
    return overrides


def _cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest and write a report.

    Returns 0 even when the data is terrible: bad data is the product, not a failure.
    ``--max-severity`` is the exception, and exists for gates like ``make verify-clean``
    rather than for everyday use.
    """
    from datetime import date

    from sot.ingest.service import ingest_paths
    from sot.rules.model import Severity
    from sot.views.exports import write_run_reports

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    result = ingest_paths(
        args.path,
        pack_id=args.pack,
        as_of=as_of,
        type_overrides=_parse_overrides(args.type_overrides),
    )

    out_dir = Path(args.out) if args.out else settings().reports_dir / result.run_id
    written = write_run_reports(result, out_dir)

    counts = result.context.flags.counts_by_severity() if result.context else {}
    summary = "  ".join(f"{name} {count}" for name, count in counts.items() if count)
    print(f"run {result.run_id}  status {result.status}")
    print(
        f"  files {len(result.files)}  records {result.record_count:,}  "
        f"quarantined {result.quarantined_count:,}"
    )
    print(f"  flags: {summary or 'none'}")
    print(f"  report: {written[-1]}")

    if args.max_severity:
        limit = Severity(args.max_severity.upper())
        worse = [flag for flag in result.flags if flag.severity.rank < limit.rank]
        if worse:
            print(f"\n{len(worse)} finding(s) above {limit.value}:")
            for flag in worse[:20]:
                print(f"  {flag.severity.value:<8} {flag.rule_code:<30} {flag.message}")
            return 1
        print(f"  nothing above {limit.value}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "health":
        return _cmd_health()
    if args.command == "ingest":
        return _cmd_ingest(args)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
