"""Schema application and the DuckDB access layer."""

from __future__ import annotations

from datetime import datetime

from sot.store.db import Database

#: Every table and view spec section 18 asks for, plus run_files, which the engine
#: needs to record which files took part in which run.
EXPECTED_OBJECTS = {
    "runs",
    "files",
    "run_files",
    "raw_rows",
    "pdf_cells",
    "quarantine",
    "std_records",
    "std_hr",
    "std_payroll",
    "std_licenses",
    "shift_segments",
    "persons",
    "links",
    "claims",
    "golden_attributes",
    "credentials",
    "pay_lines",
    "match_person_week",
    "match_person_day",
    "daily_hours",
    "flags",
    "flag_evidence",
    "decisions",
    "node_stats",
    "run_events",
}


def test_schema_creates_every_expected_object(db: Database):
    missing = EXPECTED_OBJECTS - set(db.table_names())
    assert not missing, f"schema is missing {sorted(missing)}"


def test_init_schema_is_idempotent(db: Database):
    before = db.table_names()
    db.init_schema()
    db.init_schema()
    assert db.table_names() == before


def _a_run(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "started_at": datetime(2026, 9, 21, 9, 0),
        "status": "OK",
        "pack": "testpack",
        "as_of": "2026-09-21",
        "input_digest": "deadbeef",
        "engine_version": "0.0.0",
    }


def test_insert_and_read_back(db: Database):
    assert db.insert_rows("runs", [_a_run("R-1")]) == 1
    row = db.query_one("SELECT run_id, pack FROM runs WHERE run_id = ?", ["R-1"])
    assert row == {"run_id": "R-1", "pack": "testpack"}


def test_insert_rows_tolerates_ragged_dictionaries(db: Database):
    """Optional fields are genuinely optional; a missing key is not an error."""
    db.insert_rows(
        "flags",
        [
            {
                "run_id": "R-1",
                "flag_id": "FG-1",
                "rule_code": "X",
                "severity": "INFO",
                "category": "FILE",
                "title": "t",
                "message": "m",
                "status": "OPEN",
            },
            {
                "run_id": "R-1",
                "flag_id": "FG-2",
                "rule_code": "Y",
                "severity": "WARNING",
                "category": "TIME",
                "title": "t2",
                "message": "m2",
                "status": "OPEN",
                "owner_role": "HR",
                "suggested_action": "do the thing",
            },
        ],
    )
    assert db.scalar("SELECT count(*) FROM flags") == 2
    assert db.scalar("SELECT owner_role FROM flags WHERE flag_id = 'FG-1'") is None


def test_insert_rows_of_nothing_is_a_no_op(db: Database):
    assert db.insert_rows("runs", []) == 0


def test_delete_run_clears_derived_rows_but_keeps_files_and_decisions(db: Database):
    db.insert_rows("runs", [_a_run("R-1")])
    db.insert_rows(
        "files",
        [
            {
                "file_id": "FL-1",
                "sha256": "abc",
                "original_name": "roster.csv",
                "stored_path": "/landing/abc/roster.csv",
                "size_bytes": 10,
                "media_kind": "tabular",
            }
        ],
    )
    db.insert_rows(
        "decisions",
        [
            {
                "decision_id": "D-1",
                "decision_type": "ACCEPT_MATCH",
                "key_json": "{}",
                "created_at": datetime(2026, 9, 21, 9, 0),
                "active": True,
            }
        ],
    )
    db.insert_rows(
        "claims",
        [
            {
                "run_id": "R-1",
                "claim_id": "C-1",
                "entity_type": "person",
                "entity_id": "P-1",
                "attribute": "phone",
                "source_type": "hr",
            }
        ],
    )

    db.delete_run("R-1")

    assert db.scalar("SELECT count(*) FROM claims") == 0, "derived rows should be gone"
    assert db.scalar("SELECT count(*) FROM files") == 1, "landed content outlives a run"
    assert db.scalar("SELECT count(*) FROM decisions") == 1, "human memory outlives a run"


def test_truncate_all_clears_everything(db: Database):
    db.insert_rows("runs", [_a_run("R-1")])
    db.insert_rows(
        "decisions",
        [
            {
                "decision_id": "D-1",
                "decision_type": "NOTE",
                "key_json": "{}",
                "created_at": datetime(2026, 9, 21, 9, 0),
                "active": True,
            }
        ],
    )
    db.truncate_all()
    assert db.scalar("SELECT count(*) FROM runs") == 0
    assert db.scalar("SELECT count(*) FROM decisions") == 0


def test_standardized_views_project_payload_fields(db: Database):
    """std_hr and friends are views over one generic table, so that a pack with
    different source columns reuses every node downstream of ingestion."""
    db.insert_rows(
        "std_records",
        [
            {
                "run_id": "R-1",
                "record_id": "SR-1",
                "source_type": "hr",
                "source_role": "roster",
                "file_id": "FL-1",
                "row_index": 2,
                "payload_json": '{"employee_id":"X1","last_name":"Doe","hire_date":"2020-03-02"}',
                "raw_json": "{}",
            }
        ],
    )
    row = db.query_one("SELECT employee_id, last_name, hire_date FROM std_hr")
    assert row is not None
    assert row["employee_id"] == "X1"
    assert row["last_name"] == "Doe"
    assert str(row["hire_date"]) == "2020-03-02"


def test_views_ignore_records_from_other_roles(db: Database):
    db.insert_rows(
        "std_records",
        [
            {
                "run_id": "R-1",
                "record_id": "SR-2",
                "source_type": "payroll",
                "source_role": "payroll",
                "file_id": "FL-1",
                "row_index": 2,
                "payload_json": '{"hours_paid":"36"}',
                "raw_json": "{}",
            }
        ],
    )
    assert db.scalar("SELECT count(*) FROM std_hr") == 0
    assert db.scalar("SELECT hours_paid FROM std_payroll") == 36.0
