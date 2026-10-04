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

    sub.add_parser("health", help="print engine and database status")
    return parser


def _cmd_health() -> int:
    from sot.api.routers.health import health as health_payload

    print(json.dumps(health_payload(), indent=2))
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    # Wired in phase 2, once detection and the robust reader exist.
    raise SystemExit(
        "ingest is not wired up yet (arrives in phase 2: ingestion).\n"
        f"Parsed fine though: path={args.path} as_of={args.as_of or 'today'} "
        f"pack={args.pack or settings().default_pack} overrides={args.type_overrides}"
    )


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
