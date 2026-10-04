"""The rule registry, catalog, and flag builder."""

from __future__ import annotations

import pytest

from sot.rules.builder import FlagCollector, format_message
from sot.rules.catalog import RULES, build_registry
from sot.rules.model import Aggregate, Category, Entity, Evidence, OwnerRole, Severity
from sot.rules.registry import RuleRegistry, RuleSpec

# --- the catalog ------------------------------------------------------------


def test_every_rule_in_the_spec_catalog_is_registered():
    """Declared early on purpose: it makes the documentation complete and lets the
    chaos deck demand coverage of codes whose evaluator is not written yet."""
    assert len(RULES.codes()) >= 80


def test_rule_codes_are_unique():
    with pytest.raises(ValueError, match="already registered"):
        registry = build_registry()
        registry.register(RULES.get("FILE_DUPLICATE"))


def test_every_rule_has_a_message_an_action_and_an_owner():
    """A flag nobody owns is a flag nobody acts on."""
    for spec in RULES.all():
        assert spec.message.strip(), spec.code
        assert spec.suggested_action.strip(), spec.code
        assert isinstance(spec.owner_role, OwnerRole), spec.code
        assert isinstance(spec.category, Category), spec.code
        assert spec.priority in {"P0", "P1", "P2"}, spec.code


def test_every_rule_explains_what_it_means():
    for spec in RULES.all():
        assert len(spec.meaning) > 10, spec.code


def test_conditional_severities_document_themselves():
    """The generated docs have to be able to explain why a severity varies."""
    for spec in RULES.all():
        if spec.severity_fn is not None:
            assert spec.severity_note.strip(), spec.code


def test_an_unknown_code_fails_with_a_useful_message():
    with pytest.raises(KeyError, match=r"catalog\.py"):
        RULES.get("NO_SUCH_RULE")


def test_unimplemented_rules_are_queryable():
    """So "which P0 rules are still missing" is a query, not a memory exercise."""
    assert isinstance(RULES.unimplemented("P0"), list)
    assert "FILE_DUPLICATE" not in RULES.unimplemented()


# --- severity ---------------------------------------------------------------


def test_severity_sorts_worst_first():
    order = sorted(Severity, key=lambda s: s.rank)
    assert order == [Severity.BLOCKER, Severity.CRITICAL, Severity.WARNING, Severity.INFO]


def test_only_info_is_not_above_info():
    assert not Severity.INFO.is_above_info
    assert all(s.is_above_info for s in Severity if s is not Severity.INFO)


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(90, Severity.WARNING), (168, Severity.WARNING), (200, Severity.CRITICAL)],
)
def test_excessive_hours_escalates_past_a_full_week(hours, expected):
    assert RULES.get("HOURS_EXCESSIVE_WEEK").severity_for({"hours": hours}) is expected


@pytest.mark.parametrize(
    ("days", "expected"), [(80, Severity.WARNING), (31, Severity.WARNING), (14, Severity.CRITICAL)]
)
def test_expiry_escalates_inside_thirty_days(days, expected):
    assert RULES.get("CREDENTIAL_EXPIRING").severity_for({"days_left": days}) is expected


def test_an_unlicensed_role_on_the_rota_is_only_a_warning():
    spec = RULES.get("UNMATCHED_SCHEDULE")
    assert spec.severity_for({"role_requires_credential": False}) is Severity.WARNING
    assert spec.severity_for({"role_requires_credential": True}) is Severity.CRITICAL


def test_a_scanned_page_is_not_a_blocker_when_ocr_read_it():
    spec = RULES.get("PDF_NO_TEXT_LAYER")
    assert spec.severity_for({"ocr_used": True}) is Severity.INFO
    assert spec.severity_for({}) is Severity.BLOCKER


def test_a_severity_function_that_breaks_falls_back_rather_than_losing_the_flag():
    spec = RuleSpec(
        code="X",
        severity=Severity.WARNING,
        category=Category.FILE,
        priority="P0",
        meaning="m" * 20,
        title="t",
        message="m",
        suggested_action="a",
        owner_role=OwnerRole.HR,
        severity_fn=lambda params: 1 / 0,
    )
    assert spec.severity_for({}) is Severity.WARNING


# --- messages ---------------------------------------------------------------


def test_a_message_is_filled_from_its_parameters():
    assert format_message("{a} and {b}", {"a": "x", "b": "y"}) == "x and y"


def test_a_missing_parameter_leaves_a_visible_gap_rather_than_raising():
    """An odd sentence beats losing the finding."""
    assert format_message("{a} and {b}", {"a": "x"}) == "x and {b}"


def test_a_format_spec_that_does_not_fit_its_value_still_produces_a_message():
    assert format_message("{score:.0%}", {"score": "not a number"}) == "not a number"


# --- the collector ----------------------------------------------------------


def test_a_flag_carries_everything_needed_to_act_on_it():
    collector = FlagCollector()
    collector.raise_flag(
        "FILE_DUPLICATE",
        {"filename": "a.csv", "original_name": "b.csv"},
        entities=[Entity("file", "FL-1", "a.csv")],
    )
    flag = collector.finalize()[0]
    assert "a.csv" in flag.message and "b.csv" in flag.message
    assert flag.suggested_action and flag.owner_role
    assert flag.entities[0].display == "a.csv"


def test_informational_findings_roll_up_per_file():
    """Twenty-three cards would bury the one that matters."""
    collector = FlagCollector()
    for row in range(23):
        collector.raise_flag(
            "NULL_TOKEN",
            {"filename": "roster.csv", "tokens": "N/A", "file_id": "FL-1"},
            evidence=[Evidence(file_id="FL-1", row_index=row)],
        )
    flags = collector.finalize()
    assert len(flags) == 1
    assert flags[0].occurrence_count == 23
    assert "23 cell(s)" in flags[0].message


def test_rollup_keeps_only_a_handful_of_evidence_pointers():
    collector = FlagCollector()
    for row in range(40):
        collector.raise_flag(
            "NULL_TOKEN",
            {"filename": "a.csv", "file_id": "FL-1", "tokens": "NA"},
            evidence=[Evidence(file_id="FL-1", row_index=row)],
        )
    assert len(collector.finalize()[0].evidence) == 5


def test_rollup_is_per_file_not_global():
    collector = FlagCollector()
    for file_id in ("FL-1", "FL-2"):
        collector.raise_flag(
            "NULL_TOKEN", {"filename": file_id, "file_id": file_id, "tokens": "NA"}
        )
    assert len(collector.finalize()) == 2


def test_rollup_by_column_separates_columns():
    collector = FlagCollector()
    for column in ("phone", "hire_date"):
        for _ in range(3):
            collector.raise_flag(
                "VALUE_NORMALIZED",
                {"filename": "a.csv", "file_id": "FL-1", "column": column, "example": "x"},
            )
    flags = collector.finalize()
    assert len(flags) == 2
    assert all(flag.occurrence_count == 3 for flag in flags)


def test_an_aggregate_cannot_hide_its_worst_member():
    collector = FlagCollector()
    collector.raise_flag("NULL_TOKEN", {"file_id": "FL-1", "filename": "a"}, severity=Severity.INFO)
    collector.raise_flag(
        "NULL_TOKEN", {"file_id": "FL-1", "filename": "a"}, severity=Severity.WARNING
    )
    assert collector.finalize()[0].severity is Severity.WARNING


def test_the_same_finding_keeps_its_id_across_runs():
    def build() -> str:
        collector = FlagCollector()
        collector.raise_flag(
            "FILE_DUPLICATE",
            {"filename": "a.csv", "original_name": "b.csv"},
            entities=[Entity("file", "FL-1")],
        )
        return collector.finalize()[0].flag_id

    assert build() == build()


def test_flags_come_out_worst_first():
    collector = FlagCollector()
    collector.raise_flag("NULL_TOKEN", {"file_id": "F", "filename": "a"})
    collector.raise_flag("FILE_TYPE_UNKNOWN", {"filename": "b"})
    assert [flag.severity for flag in collector.finalize()] == [Severity.BLOCKER, Severity.INFO]


def test_counts_and_worst_severity_are_reported():
    collector = FlagCollector()
    collector.raise_flag("FILE_TYPE_UNKNOWN", {"filename": "b"})
    collector.raise_flag("NULL_TOKEN", {"file_id": "F", "filename": "a"})
    assert collector.worst_severity() is Severity.BLOCKER
    assert collector.counts_by_severity()["BLOCKER"] == 1
    assert len(collector.above_info()) == 1


def test_an_empty_run_has_no_worst_severity():
    assert FlagCollector().worst_severity() is None


def test_a_registry_is_independent_of_the_shared_one():
    registry = RuleRegistry()
    registry.register(
        RuleSpec(
            code="LOCAL",
            severity=Severity.INFO,
            category=Category.FILE,
            priority="P0",
            meaning="a local rule for testing",
            title="t",
            message="hello {who}",
            suggested_action="a",
            owner_role=OwnerRole.HR,
            aggregate=Aggregate.NONE,
        )
    )
    collector = FlagCollector(registry)
    collector.raise_flag("LOCAL", {"who": "world"})
    assert collector.finalize()[0].message == "hello world"


def test_the_generated_rules_document_is_up_to_date():
    """Documentation derived from the registry cannot drift - unless nobody regenerates
    it, which is what this catches."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "gen_rules_doc.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
