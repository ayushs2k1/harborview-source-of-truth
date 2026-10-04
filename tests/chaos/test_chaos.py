"""Running the chaos deck.

Every mutation is applied to its own copy of the clean sample and ingested at the
pinned as-of date, so results never drift with the calendar and no mutation can
affect another.

Two assertions per mutation, and the second is the one that catches over-reaction:
the expected codes must appear, and the forbidden ones must not. A system that panics
about a renamed column header is as useless as one that misses a ghost employee.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from sot.ingest.service import ingest_paths
from sot.rules.catalog import RULES
from sot.store.db import Database
from tests.chaos.deck import DECK, Mutation, prepare

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PINNED_AS_OF = date(2026, 9, 21)

#: Codes no mutation should ever produce. NODE_FAILED means a step crashed, which is
#: a bug rather than a finding, so demanding coverage of it would demand a bug.
NEVER_EXPECTED = {"NODE_FAILED"}

pytestmark = pytest.mark.chaos


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("chaos")


@pytest.fixture(scope="module")
def results(workspace: Path) -> dict[str, dict]:
    """Run every mutation once; the tests then interrogate the outcome."""
    database = Database(workspace / "chaos.duckdb")
    outcomes: dict[str, dict] = {}
    try:
        for mutation in DECK:
            target = prepare(mutation, workspace)
            result = ingest_paths(
                target,
                pack_id="healthcare_ny",
                as_of=mutation.as_of or PINNED_AS_OF,
                db=database,
            )
            observed = {flag.rule_code for flag in result.flags}
            missing = sorted(set(mutation.expect_codes) - observed)
            forbidden = sorted(set(mutation.forbid_codes) & observed)
            outcomes[mutation.id] = {
                "id": mutation.id,
                "description": mutation.description,
                "expect_codes": list(mutation.expect_codes),
                "forbid_codes": list(mutation.forbid_codes),
                "observed": sorted(observed),
                "missing": missing,
                "forbidden_seen": forbidden,
                "crashed": [
                    flag.message for flag in result.flags if flag.rule_code == "NODE_FAILED"
                ],
                "passed": not missing and not forbidden,
                "status": result.status,
            }
    finally:
        database.close()
    _write_report(outcomes)
    return outcomes


def _write_report(outcomes: dict[str, dict]) -> None:
    """Write the coverage report the UI reads and a human can skim."""
    from datetime import datetime

    covered = {code for outcome in outcomes.values() for code in outcome["observed"]}
    p0 = [spec.code for spec in RULES.by_priority("P0") if spec.code not in NEVER_EXPECTED]
    uncovered = sorted(set(p0) - covered)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mutations": sorted(outcomes.values(), key=lambda item: item["id"]),
        "passed": sum(1 for item in outcomes.values() if item["passed"]),
        "failed": sum(1 for item in outcomes.values() if not item["passed"]),
        "p0_codes": len(p0),
        "p0_covered": len(set(p0) & covered),
        "p0_uncovered": uncovered,
    }

    reports = REPO_ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "chaos_coverage.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Chaos coverage",
        "",
        f"{payload['passed']} of {len(outcomes)} mutations pass. "
        f"{payload['p0_covered']} of {payload['p0_codes']} P0 rules are exercised.",
        "",
        "Each mutation breaks the clean sample in one specific way. The *must not appear*",
        "column is the half that catches over-reaction: renaming a column header should",
        "change nothing at all.",
        "",
        "| | Mutation | Expected | Must not appear | Result |",
        "|---|---|---|---|---|",
    ]
    for item in payload["mutations"]:
        lines.append(
            f"| `{item['id']}` | {item['description']} "
            f"| {', '.join(f'`{code}`' for code in item['expect_codes']) or '—'} "
            f"| {', '.join(f'`{code}`' for code in item['forbid_codes']) or '—'} "
            f"| {'pass' if item['passed'] else '**FAIL**'} |"
        )
    if uncovered:
        lines.extend(["", "## P0 rules with no mutation", ""])
        lines.extend(f"- `{code}`" for code in uncovered)
    (reports / "chaos_coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize("mutation", DECK, ids=lambda item: item.id)
def test_mutation(mutation: Mutation, results: dict[str, dict]):
    outcome = results[mutation.id]
    assert not outcome["crashed"], f"{mutation.id} crashed a step: {outcome['crashed']}"
    assert not outcome["missing"], (
        f"{mutation.id} ({mutation.description}) did not raise {outcome['missing']}. "
        f"It raised: {outcome['observed']}"
    )
    assert not outcome["forbidden_seen"], (
        f"{mutation.id} ({mutation.description}) raised {outcome['forbidden_seen']}, "
        "which it must not"
    )


def test_every_p0_rule_is_exercised_by_a_mutation(results: dict[str, dict]):
    """The spec's coverage rule. This list must be empty before the deck is done."""
    covered = {code for outcome in results.values() for code in outcome["observed"]}
    expected = {spec.code for spec in RULES.by_priority("P0")} - NEVER_EXPECTED
    uncovered = sorted(expected - covered)
    assert uncovered == [], f"no mutation exercises {uncovered}"


def test_no_mutation_ever_crashes_the_run(results: dict[str, dict]):
    """Principle 1. A broken file is a finding, never an exception."""
    crashed = {item: outcome["crashed"] for item, outcome in results.items() if outcome["crashed"]}
    assert crashed == {}
