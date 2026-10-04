"""Guard: nothing from the sample data may be hard-coded into the engine.

The judges hand over their own files at judging time. Any sample name, identifier, or
date baked into ``sot/`` is a behaviour that will not reproduce on their data, and it
would not necessarily fail loudly - it would just quietly work for us and not for them.
So this is checked mechanically rather than left to discipline.

Allowed to contain sample values: ``packs/`` (crosswalk seeds are configuration),
``scripts/`` (the generator writes the samples), ``data/``, and ``tests/``.

A line ending in ``# sample-ok: <reason>`` is exempt. Reach for it only with a reason
that would survive being read out loud.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

#: Literals from the brief's example rows (spec section 5).
#:
#: "Harborview" alone is deliberately absent: the spec names the application after the
#: client, so the product title is not a data leak. The facility and organisation forms
#: of the name are caught by SAMPLE_PATTERNS and by Bayside/Riverdale below.
BRIEF_TOKENS = [
    "Bayside",
    "Riverdale",
    "Sofia",
    "Reyes",
    "Marcus",
    "Marc Bell",
    "BYS",
    "RVD",
]

#: Shapes of identifier and contact values in the samples.
SAMPLE_PATTERNS = [
    (r"\bE\d{3}\b", "roster employee id"),
    (r"\bP-\d{4}\b", "payroll id"),
    (r"\b(?:RN|LPN|CNA)-\d{5,}\b", "credential number"),
    (r"\b(?:718|347)-555-\d{4}\b", "sample phone number"),
    (r"\b2026-09-(?:14|20|21)\b", "sample pay period date"),
    (r"\b2027-05-31\b", "sample expiry date"),
    (r"\b2026-12-31\b", "sample expiry date"),
    (r"Harborview\s+(?:Care|Bayside|Riverdale)", "client or facility name"),
]

#: Columns in the generated samples whose values must never appear in engine code.
IDENTIFYING_COLUMNS = {
    "first_name",
    "last_name",
    "middle_name",
    "employee_name",
    "name_on_license",
    "name_on_credential",
    "driver_name",
    "employee_id",
    "driver_id",
    "payroll_id",
    "license_number",
    "cdl_number",
    "credential_number",
    "facility",
    "facility_code",
    "terminal",
    "phone",
}

EXEMPT_MARKER = "# sample-ok:"


def _engine_sources(repo_root: Path) -> list[Path]:
    return sorted(p for p in (repo_root / "sot").rglob("*.py"))


def _sample_literals(repo_root: Path) -> set[str]:
    """Values pulled out of the generated samples, so the guard grows with the data."""
    literals: set[str] = set()
    samples = repo_root / "data" / "samples"
    if not samples.is_dir():
        return literals
    for path in sorted(samples.rglob("*.csv")):
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as handle:
                for row in csv.DictReader(handle):
                    for column, value in row.items():
                        if column and column.strip().lower() in IDENTIFYING_COLUMNS:
                            token = (value or "").strip()
                            # Short tokens produce false positives against ordinary
                            # code; identifier shapes are covered by SAMPLE_PATTERNS.
                            if len(token) >= 5 and any(ch.isalpha() for ch in token):
                                literals.add(token)
        except (OSError, csv.Error):
            continue
    return literals


def _violations(path: Path, needles: list[tuple[re.Pattern[str], str]]) -> list[str]:
    found: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if EXEMPT_MARKER in line:
            continue
        for pattern, label in needles:
            if pattern.search(line):
                found.append(f"{path}:{lineno}: {label} -> {line.strip()[:90]}")
    return found


def test_engine_contains_no_sample_data(repo_root: Path):
    needles: list[tuple[re.Pattern[str], str]] = [
        (re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE), f"sample literal {token!r}")
        for token in BRIEF_TOKENS
    ]
    needles += [(re.compile(pattern), label) for pattern, label in SAMPLE_PATTERNS]
    needles += [
        (re.compile(rf"\b{re.escape(literal)}\b"), f"value from the generated samples {literal!r}")
        for literal in sorted(_sample_literals(repo_root))
    ]

    offences = [v for source in _engine_sources(repo_root) for v in _violations(source, needles)]
    assert not offences, (
        "Sample data found in the engine. Move it into a pack, a crosswalk, or a "
        "fixture:\n  " + "\n  ".join(offences)
    )


def test_the_guard_can_actually_see_a_violation(tmp_path: Path):
    """A guard that cannot fail is not a guard."""
    planted = tmp_path / "bad.py"
    planted.write_text('FACILITY = "Bayside"\n')
    needles = [(re.compile(r"\bBayside\b", re.IGNORECASE), "sample literal")]
    assert _violations(planted, needles)


def test_the_exemption_marker_works(tmp_path: Path):
    planted = tmp_path / "ok.py"
    planted.write_text('FACILITY = "Bayside"  # sample-ok: documented reason\n')
    needles = [(re.compile(r"\bBayside\b", re.IGNORECASE), "sample literal")]
    assert not _violations(planted, needles)


@pytest.mark.parametrize("directory", ["packs", "scripts", "data", "tests"])
def test_exempt_directories_are_not_scanned(repo_root: Path, directory: str):
    """Documents the boundary: these are config and fixtures, where samples belong."""
    scanned = {p.parts[len(repo_root.parts)] for p in _engine_sources(repo_root)}
    assert directory not in scanned


def test_the_product_name_is_allowed_but_the_facility_name_is_not(tmp_path: Path):
    """The app is named after the client by the spec; its facilities are still data."""
    needles = [(re.compile(pattern), label) for pattern, label in SAMPLE_PATTERNS]

    product_title = tmp_path / "title.py"
    product_title.write_text('APP_TITLE = "Harborview Source of Truth"\n')
    assert not _violations(product_title, needles)

    facility_literal = tmp_path / "facility.py"
    facility_literal.write_text('HOME = "Harborview Bayside"\n')
    assert _violations(facility_literal, needles)
