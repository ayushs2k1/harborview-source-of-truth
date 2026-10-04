"""Matching column headings to contract fields."""

from __future__ import annotations

from sot.ingest.contracts import Column, Contract, header_key
from sot.ingest.headers import (
    METHOD_EXACT,
    METHOD_FUZZY,
    METHOD_LEARNED,
    map_headers,
    signature_score,
)

PAYROLL_HEADER = [
    "payroll_id",
    "employee_name",
    "job_code",
    "facility_code",
    "period_start",
    "period_end",
    "hours_paid",
]


def test_header_key_folds_case_punctuation_and_accents():
    assert header_key("Pay Period Start") == header_key("pay_period_start")
    assert header_key("Hours  Paid") == header_key("HOURS-PAID")
    assert header_key("Facilité") == "facilite"


def test_canonical_names_match_exactly(pack):
    mapping = map_headers(PAYROLL_HEADER, pack.contract("payroll"))
    assert set(mapping.by_canonical) == set(PAYROLL_HEADER)
    assert all(match.method == METHOD_EXACT for match in mapping.by_canonical.values())
    assert not mapping.missing_required


def test_synonyms_match_exactly(pack):
    """M01: renamed headers must not produce a blocker, and must read identically."""
    renamed = [
        "Pay ID",
        "Employee",
        "Position Code",
        "Cost Centre",
        "Week Start",
        "Week End",
        "Hrs",
    ]
    mapping = map_headers(renamed, pack.contract("payroll"))
    assert set(mapping.by_canonical) == set(PAYROLL_HEADER)
    assert not mapping.missing_required


def test_column_order_does_not_matter(pack):
    """M02."""
    forward = map_headers(PAYROLL_HEADER, pack.contract("payroll"))
    backward = map_headers(list(reversed(PAYROLL_HEADER)), pack.contract("payroll"))
    assert set(forward.by_canonical) == set(backward.by_canonical)
    assert forward.score == backward.score


def test_a_typo_is_matched_by_similarity(pack):
    mapping = map_headers(
        ["employee_nam", "job_code", "facility_code", "period_start", "period_end", "hours_paid"],
        pack.contract("payroll"),
    )
    match = mapping.by_canonical["employee_name"]
    assert match.method == METHOD_FUZZY
    assert match.score >= 0.90


def test_an_unrelated_column_is_kept_not_dropped(pack):
    """M03: we do not understand it, which is not the same as it not mattering."""
    mapping = map_headers([*PAYROLL_HEADER, "Union Local"], pack.contract("payroll"))
    assert [match.raw for match in mapping.unmapped] == ["Union Local"]
    assert not mapping.missing_required


def test_two_columns_claiming_one_field_keeps_the_better_match(pack):
    mapping = map_headers([*PAYROLL_HEADER, "hours"], pack.contract("payroll"))
    assert mapping.by_canonical["hours_paid"].raw == "hours_paid"
    assert "hours_paid" in mapping.ambiguous
    assert any(match.raw == "hours" for match in mapping.unmapped)


def test_a_missing_required_column_is_reported(pack):
    """M04: dropping the hours column blocks payroll and nothing else."""
    without_hours = [name for name in PAYROLL_HEADER if name != "hours_paid"]
    mapping = map_headers(without_hours, pack.contract("payroll"))
    assert mapping.missing_required == ["hours_paid"]


def test_a_learned_decision_wins_over_everything(pack):
    """A human who has already answered this should not be overruled by a fuzzy match."""
    mapping = map_headers(
        [
            "Local Ref",
            "employee_name",
            "job_code",
            "facility_code",
            "period_start",
            "period_end",
            "hours_paid",
        ],
        pack.contract("payroll"),
        learned={header_key("Local Ref"): "payroll_id"},
    )
    match = mapping.by_canonical["payroll_id"]
    assert match.method == METHOD_LEARNED
    assert match.raw == "Local Ref"


def test_a_single_name_column_satisfies_the_roster_requirement(pack):
    """A roster that does not split given and family names is still a usable roster."""
    mapping = map_headers(["Name", "Job Title", "Facility"], pack.contract("hr"))
    assert mapping.missing_required == []
    assert "employee_name" in mapping.by_canonical


def test_a_roster_with_no_name_at_all_is_blocked(pack):
    mapping = map_headers(["Job Title", "Facility"], pack.contract("hr"))
    assert mapping.missing_required


def test_blank_and_empty_headings_are_ignored(pack):
    mapping = map_headers(["payroll_id", "", "  ", "employee_name"], pack.contract("payroll"))
    assert set(mapping.by_canonical) == {"payroll_id", "employee_name"}


def test_signature_score_weights_required_columns_more():
    """Otherwise adding optional synonyms would dilute a contract's own signature."""
    contract = Contract(
        source="x",
        role="payroll",
        columns=(
            Column("needed", required=True),
            Column("spare_one"),
            Column("spare_two"),
        ),
    )
    assert signature_score(contract, {"needed"}) > signature_score(
        contract, {"spare_one", "spare_two"}
    )


def test_signature_score_does_not_penalise_extra_file_columns(pack):
    """A real export has columns we have never heard of. That is not evidence against."""
    base = map_headers(PAYROLL_HEADER, pack.contract("payroll")).score
    with_extras = map_headers(
        [*PAYROLL_HEADER, "Union Local", "GL Account", "Shift Diff"], pack.contract("payroll")
    ).score
    assert with_extras == base
