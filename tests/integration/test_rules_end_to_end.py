"""The rules, end to end against the fixtures.

Phase 5's exit criterion is two sentences: the clean set raises nothing above INFO at
the pinned as-of date, and the messy set raises the expected findings with the right
severities. Both are asserted here.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sot.ingest.service import ingest_paths
from sot.rules.catalog import RULES
from sot.store.db import Database

AS_OF = date(2026, 9, 21)


# Module-scoped: a full ingest is a second of work, and these tests all interrogate
# the same two runs rather than changing anything about them.
@pytest.fixture(scope="module")
def run(tmp_path_factory):
    database = Database(tmp_path_factory.mktemp("rules") / "rules.duckdb")

    def ingest(target, **kwargs):
        return ingest_paths(target, pack_id="healthcare_ny", as_of=AS_OF, db=database, **kwargs)

    ingest.db = database  # type: ignore[attr-defined]
    yield ingest
    database.close()


@pytest.fixture(scope="module")
def samples() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "healthcare"


@pytest.fixture(scope="module")
def clean(run, samples):
    return run(samples / "clean")


@pytest.fixture(scope="module")
def messy(run, samples):
    return run(samples / "messy")


def codes(result) -> set[str]:
    return {flag.rule_code for flag in result.flags}


def severity_of(result, code: str) -> str:
    return next(flag.severity.value for flag in result.flags if flag.rule_code == code)


def message_of(result, code: str) -> str:
    return next(flag.message for flag in result.flags if flag.rule_code == code)


# --- the headline criteria --------------------------------------------------


def test_the_clean_set_raises_nothing_above_info(clean):
    """Phase 5's exit criterion, and the control for every later change."""
    above = [
        (flag.severity.value, flag.rule_code, flag.message) for flag in clean.flags_above_info()
    ]
    assert above == []


def test_the_clean_set_still_reconciles_perfectly(clean):
    from sot.match.fourway import STATUS_MATCHED

    statuses = {week.status for week in clean.match.weeks}
    assert statuses == {STATUS_MATCHED}


def test_the_clean_set_builds_a_full_ledger(clean):
    assert len(clean.golden) > 150
    assert len(clean.credentials) == 10
    assert len(clean.pay_lines) == 11
    assert all(credential.in_service for credential in clean.credentials)


@pytest.mark.parametrize(
    ("code", "severity"),
    [
        ("UNMATCHED_PAYROLL", "CRITICAL"),
        ("UNMATCHED_SCHEDULE", "CRITICAL"),
        ("DUPLICATE_PAY_PERIOD", "CRITICAL"),
        ("CREDENTIAL_EXPIRED", "CRITICAL"),
        ("WORKED_AFTER_EXPIRY", "CRITICAL"),
        ("LICENSED_ROLE_NO_CREDENTIAL", "CRITICAL"),
        ("RN_8H_COVERAGE_GAP", "CRITICAL"),
        ("HPRD_BELOW_MINIMUM", "CRITICAL"),
        ("CREDENTIAL_EXPIRING", "WARNING"),
        ("VERIFICATION_STALE", "WARNING"),
        ("HR_LICENSE_EXPIRY_STALE", "WARNING"),
        ("HOURS_VARIANCE", "WARNING"),
        ("PAID_NOT_SCHEDULED", "WARNING"),
        ("PBJ_UNALLOCATED_HOURS", "WARNING"),
        ("PBJ_TRACEABILITY_VARIANCE", "WARNING"),
        ("CODE_UNKNOWN_FACILITY", "WARNING"),
        ("CNA_HOURS_EXCLUDED_UNCERTIFIED", "WARNING"),
        ("CNA_RECERT_EVIDENCE_INSUFFICIENT", "WARNING"),
        ("PTO_ON_SCHEDULE", "INFO"),
        ("SHIFT_NOT_IN_FOOTNOTE", "INFO"),
        ("PERSON_ON_MULTIPLE_PAGES", "INFO"),
        ("CNA_EXPIRY_NOT_MONTH_END", "INFO"),
    ],
)
def test_the_messy_set_raises_each_planted_problem(messy, code: str, severity: str):
    assert code in codes(messy), f"{code} was not raised"
    assert severity_of(messy, code) == severity


# --- the messages a human actually reads ------------------------------------


def test_the_ghost_payroll_message_names_the_row_the_person_and_the_money(messy):
    message = message_of(messy, "UNMATCHED_PAYROLL")
    assert "P-3012" in message and "32" in message
    assert "no matching person exists in the roster" in message


def test_the_expiry_message_counts_the_shifts_worked_after_it(messy):
    message = message_of(messy, "WORKED_AFTER_EXPIRY")
    assert "expired" in message and "shift(s)" in message
    assert "Sep 19" in message


def test_the_stale_expiry_message_names_both_dates(messy):
    message = message_of(messy, "HR_LICENSE_EXPIRY_STALE")
    assert "the roster says" in message.lower()
    assert "verification service says" in message


def test_the_coverage_message_names_what_was_lost(messy):
    message = message_of(messy, "RN_8H_COVERAGE_GAP")
    assert "no RN on duty" in message
    assert "Sep 20" in message


def test_a_variance_explained_by_leave_is_only_informational(messy):
    """The week reconciles once the leave is counted. It is explained, not wrong."""
    variances = [flag for flag in messy.flags if flag.rule_code == "HOURS_VARIANCE"]
    explained = [flag for flag in variances if flag.params.get("explained_by_pto")]
    assert explained, "the planted PTO week should appear"
    assert all(flag.severity.value == "INFO" for flag in explained)
    assert any(flag.severity.value == "WARNING" for flag in variances), "and one should not be"


def test_dates_read_as_prose_not_as_log_lines(messy):
    """These are read by a director of nursing between shifts, not by a machine."""
    import re

    message = message_of(messy, "CREDENTIAL_EXPIRING")
    assert re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", message), message
    assert not re.search(r"\d{4}-\d{2}-\d{2}", message), message


# --- things that must NOT be raised -----------------------------------------


def test_a_float_is_not_reported_as_a_facility_conflict(clean, messy):
    """Somebody legitimately working at two sites is the hardest person to attribute
    hours for, and reporting them as a conflict would be exactly backwards."""
    assert "FACILITY_CONFLICT" not in codes(clean)
    assert "FACILITY_CONFLICT" not in codes(messy)
    assert "PERSON_ON_MULTIPLE_PAGES" in codes(clean)


def test_nobody_is_reported_as_working_before_they_were_hired(clean, messy):
    assert "ACTIVITY_BEFORE_HIRE" not in codes(clean)
    assert "ACTIVITY_BEFORE_HIRE" not in codes(messy)


def test_hours_per_resident_is_reported_per_site_not_per_day(messy):
    """Seven identical cards for one week below the minimum would bury everything."""
    hprd = [flag for flag in messy.flags if flag.rule_code == "HPRD_BELOW_MINIMUM"]
    assert len(hprd) <= 6, "two sites and three staffing categories at most"
    assert all(flag.params.get("days", 0) >= 1 for flag in hprd)


def test_no_rule_crashed(clean, messy):
    """A rule that raises becomes a BLOCKER naming itself, which is better than
    losing the report - but it should not be happening."""
    for result in (clean, messy):
        failures = [flag for flag in result.flags if flag.rule_code == "NODE_FAILED"]
        assert failures == [], [flag.message for flag in failures]


# --- flag plumbing ----------------------------------------------------------


def test_every_flag_carries_an_action_and_an_owner(messy):
    for flag in messy.flags:
        assert flag.suggested_action.strip(), flag.rule_code
        assert flag.owner_role, flag.rule_code


def test_flag_ids_are_stable_between_runs(run, samples):
    first = run(samples / "messy")
    second = run(samples / "messy")
    assert {flag.flag_id for flag in first.flags} == {flag.flag_id for flag in second.flags}


def test_flags_and_their_evidence_reach_the_database(messy, run):
    result = messy
    stored = run.db.scalar("SELECT count(*) FROM flags WHERE run_id = ?", [result.run_id])
    assert stored == len(result.flags)
    assert run.db.scalar("SELECT count(*) FROM flag_evidence WHERE run_id = ?", [result.run_id]) > 0


def test_the_derived_tables_are_written(clean, run):
    result = clean
    for table, minimum in (
        ("claims", 200),
        ("golden_attributes", 150),
        ("credentials", 10),
        ("pay_lines", 11),
        ("match_person_week", 11),
        ("match_person_day", 46),
        ("daily_hours", 46),
    ):
        count = run.db.scalar(f"SELECT count(*) FROM {table} WHERE run_id = ?", [result.run_id])
        assert count >= minimum, f"{table} has {count}"


def test_node_statistics_cover_every_step(clean, run):
    result = clean
    nodes = {
        row["node_id"]
        for row in run.db.query("SELECT node_id FROM node_stats WHERE run_id = ?", [result.run_id])
    }
    assert {"intake", "resolve", "ledger", "match", "staffing", "rules"} <= nodes


# --- coverage of the catalog ------------------------------------------------


def test_every_p0_rule_can_be_raised_by_something():
    """Declared-but-unimplemented is fine during a build and not fine at the end."""
    assert RULES.unimplemented("P0") == []


def test_only_the_stretch_rule_remains():
    assert RULES.unimplemented() == ["VOLUME_DROP"]


def test_the_messy_set_exercises_a_good_share_of_the_catalog(messy):
    assert len(codes(messy)) >= 25
