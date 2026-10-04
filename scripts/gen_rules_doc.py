"""Generate ``docs/RULES.md`` from the rule registry.

The documentation is derived rather than written, so it cannot drift from the code.
A test asserts the committed file matches what this produces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sot.rules.catalog import RULES  # noqa: E402
from sot.rules.model import Category  # noqa: E402

CATEGORY_TITLES = {
    Category.FILE: "File and structure",
    Category.FORMAT: "Format",
    Category.IDENTITY: "Identity",
    Category.CROSS_SOURCE: "Cross-source (the four-way match)",
    Category.TIME: "Time",
    Category.PDF: "Schedule PDF",
    Category.DOMAIN: "Domain",
}


def render() -> str:
    specs = RULES.all()
    done = [spec for spec in specs if spec.implemented]
    lines = [
        "# Rules",
        "",
        "Generated from the rule registry by `make docs`. Do not edit by hand.",
        "",
        f"{len(specs)} rules, {len(done)} with an evaluator so far.",
        "",
        "Severity means: **BLOCKER** a file or page could not be processed, and only "
        "that one is affected · **CRITICAL** compliance, safety, or money is at risk · "
        "**WARNING** needs human judgement · **INFO** auto-fixed or informational, "
        "aggregated so the inbox stays readable.",
        "",
        "## Coverage",
        "",
        "| Priority | Rules | With an evaluator |",
        "|---|---|---|",
    ]
    for priority in ("P0", "P1", "P2"):
        group = RULES.by_priority(priority)
        lines.append(f"| {priority} | {len(group)} | {len([s for s in group if s.implemented])} |")

    pending = RULES.unimplemented("P0")
    lines.extend(["", f"P0 rules still to implement: {len(pending)}", ""])
    if pending:
        lines.append("```")
        for index in range(0, len(pending), 4):
            lines.append("  ".join(f"{code:<34}" for code in pending[index : index + 4]).rstrip())
        lines.append("```")
        lines.append("")

    for category in Category:
        group = RULES.by_category(category)
        if not group:
            continue
        lines.extend([f"## {CATEGORY_TITLES.get(category, category.value)}", ""])
        lines.append("| Code | Severity | Pri | Owner | Meaning |")
        lines.append("|---|---|---|---|---|")
        for spec in group:
            severity = spec.severity.value
            if spec.severity_fn is not None:
                severity = f"{severity}†"
            mark = "" if spec.implemented else " *(pending)*"
            lines.append(
                f"| `{spec.code}`{mark} | {severity} | {spec.priority} | "
                f"{spec.owner_role.value} | {spec.meaning} |"
            )
        notes = [spec for spec in group if spec.severity_fn is not None]
        if notes:
            lines.extend(["", "† Severity depends on context:", ""])
            for spec in notes:
                lines.append(f"- `{spec.code}` — {spec.severity_note}")
        lines.append("")

    lines.extend(["## Messages", ""])
    lines.append("What each rule says, with the values filled in at the time.")
    lines.append("")
    for spec in specs:
        lines.append(f"**`{spec.code}`** — {spec.title}")
        lines.append("")
        lines.append(f"> {spec.message}")
        lines.append("")
        lines.append(f"*Action:* {spec.suggested_action}")
        if spec.params_from_pack:
            keys = ", ".join(f"`{key}`" for key in spec.params_from_pack)
            lines.append(f" · *Configured by:* {keys}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(REPO_ROOT / "docs" / "RULES.md"))
    parser.add_argument(
        "--check", action="store_true", help="fail if the file on disk is out of date"
    )
    args = parser.parse_args()

    content = render()
    path = Path(args.out)
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != content:
            print(f"{path} is out of date. Run: make docs")
            return 1
        print(f"{path} is up to date")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path} ({len(RULES.codes())} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
