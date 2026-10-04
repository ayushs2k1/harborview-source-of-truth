"""Ingestion end to end.

Most of these are mutations from the chaos deck applied at the file level. They run
here rather than in the deck itself because they are what phase 2 is responsible for,
and a reader regression should fail the ordinary test run, not only ``make chaos``.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pytest

from sot.ingest.service import ingest_paths
from sot.rules.model import Severity
from sot.store.db import Database

AS_OF = date(2026, 9, 21)

PAYROLL = (
    "payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid\n"
    'P-3001,"REYES, SOFIA",RN,BYS,2026-09-14,2026-09-20,36\n'
    'P-3002,"BELL, MARCUS",CNA,RVD,2026-09-14,2026-09-20,40\n'
)
ROSTER = (
    "employee_id,first_name,last_name,job_title,facility,phone,license_number,"
    "license_expiration,hire_date\n"
    "E201,Sofia,Reyes,Registered Nurse,Harborview Bayside,718-555-0201,RN-551203,"
    "2027-05-31,2020-03-02\n"
)


@pytest.fixture()
def run(tmp_path: Path):
    """Ingest into a database of this test's own."""
    database = Database(tmp_path / "run.duckdb")

    def ingest(target, **kwargs):
        return ingest_paths(target, pack_id="healthcare_ny", as_of=AS_OF, db=database, **kwargs)

    ingest.db = database  # type: ignore[attr-defined]
    yield ingest
    database.close()


def records_of(result, source: str) -> list[dict]:
    import json

    return [
        json.loads(record["payload_json"])
        for read in result.reads
        if read.detection.source == source
        for record in read.records
    ]


# --- the headline criteria --------------------------------------------------


def test_the_clean_set_ingests_with_nothing_above_info(run, sample_dir):
    """Phase 2's exit criterion, and the baseline every later phase measures against."""
    result = run(sample_dir / "clean")
    assert result.status == "OK"
    assert result.flags_above_info() == []
    assert result.record_count == 48
    assert result.quarantined_count == 0


def test_the_messy_set_raises_the_planted_reader_problem(run, sample_dir):
    result = run(sample_dir / "messy")
    assert "ROW_DELIMITER_REPAIRED" in result.codes()
    assert result.status == "OK"


def test_every_file_in_the_samples_is_classified(run, sample_dir):
    for folder in ("clean", "messy"):
        result = run(sample_dir / folder)
        tabular = [item for item in result.files if item.media_kind == "tabular"]
        assert len(result.reads) == len(tabular), folder


def test_file_order_cannot_change_the_result(run, sample_dir):
    """Principle 9. The three ways this breaks - dict order, set order, and
    first-seen-wins logic - are all invisible until someone re-runs and gets a
    different answer."""
    paths = sorted((sample_dir / "clean").iterdir())

    def canonical(result) -> tuple:
        payloads = sorted(
            record["payload_json"] for read in result.reads for record in read.records
        )
        flags = sorted((flag.rule_code, flag.message) for flag in result.flags)
        return (tuple(payloads), tuple(flags), result.record_count)

    shuffled = list(paths)
    random.Random(7).shuffle(shuffled)
    assert canonical(run(paths)) == canonical(run(shuffled))


# --- file-level mutations ---------------------------------------------------


def test_renamed_headers_change_nothing(run, make_files):
    """M01: synonyms must not produce a blocker, and the data must be identical."""
    renamed = PAYROLL.replace(
        "payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid",
        "Pay ID,Employee,Position Code,Cost Centre,Week Start,Week End,Hrs",
    )
    base = run(make_files({"a.csv": PAYROLL}, "base"))
    other = run(make_files({"a.csv": renamed}, "renamed"))
    assert records_of(base, "payroll") == records_of(other, "payroll")
    assert not other.flags_above_info()


def test_reordered_columns_change_nothing(run, make_files):
    """M02. Reordered through a CSV writer: a naive split on commas would break the
    quoted name field and test nothing but the test's own bug."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(PAYROLL)))
    order = [6, 0, 5, 1, 4, 2, 3]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        if row:
            writer.writerow([row[index] for index in order])

    base = run(make_files({"a.csv": PAYROLL}, "base"))
    other = run(make_files({"a.csv": buffer.getvalue()}, "reordered"))
    assert records_of(base, "payroll") == records_of(other, "payroll")


def test_an_extra_column_is_kept_rather_than_dropped(run, make_files):
    """M03: a column we do not understand may be the thing that explains a discrepancy."""
    text = PAYROLL.replace("hours_paid", "hours_paid,union_local").replace(",36", ",36,L1199")
    text = text.replace(",40", ",40,L1199")
    result = run(make_files({"a.csv": text}))
    assert "HEADER_UNMAPPED_COLUMN" in result.codes()
    assert records_of(result, "payroll")[0]["extra.unionlocal"] == "L1199"


def test_a_missing_required_column_blocks_only_its_own_file(run, make_files):
    """M04: payroll loses its hours column; the roster still loads."""
    without_hours = (
        "\n".join(
            ",".join(part for index, part in enumerate(line.split(",")) if index != 6)
            for line in PAYROLL.strip().splitlines()
        )
        + "\n"
    )
    result = run(make_files({"payroll.csv": without_hours, "roster.csv": ROSTER}))
    assert "HEADER_REQUIRED_MISSING" in result.codes()
    assert records_of(result, "hr"), "the roster must still be read"
    assert not records_of(result, "payroll")


def test_an_unquoted_name_is_repaired(run, make_files):
    """M05."""
    text = PAYROLL.replace('"REYES, SOFIA"', "REYES, SOFIA")
    result = run(make_files({"a.csv": text}))
    assert "ROW_DELIMITER_REPAIRED" in result.codes()
    payload = records_of(result, "payroll")[0]
    # Stored in display order once parsed, with the comparison key beside it.
    assert payload["employee_name"] == "Sofia Reyes"
    assert payload["employee_name__key"] == "reyes sofia"


def test_a_bom_and_windows_line_endings_change_nothing(run, make_files):
    """M06."""
    base = run(make_files({"a.csv": PAYROLL}, "base"))
    other = run(make_files({"a.csv": PAYROLL.replace("\n", "\r\n").encode("utf-8-sig")}, "crlf"))
    assert records_of(base, "payroll") == records_of(other, "payroll")
    assert not other.flags_above_info()


def test_a_latin1_file_keeps_its_accents(run, make_files):
    """M07."""
    text = PAYROLL.replace('"REYES, SOFIA"', '"PEÑA, JOSÉ"')
    result = run(make_files({"a.csv": text.encode("cp1252")}))
    assert "ENCODING_FALLBACK" in result.codes()
    payload = records_of(result, "payroll")[0]
    assert payload["employee_name"] == "José Peña", "the accents have to survive"
    assert payload["employee_name__family"] == "Peña"


def test_a_tab_delimited_file_reads_the_same(run, make_files):
    """M08."""
    tabbed = (
        "\n".join(
            "\t".join(field.strip('"') for field in _split_csv(line))
            for line in PAYROLL.strip().splitlines()
        )
        + "\n"
    )
    base = run(make_files({"a.csv": PAYROLL}, "base"))
    other = run(make_files({"a.tsv": tabbed}, "tabbed"))
    assert records_of(base, "payroll") == records_of(other, "payroll")


def _split_csv(line: str) -> list[str]:
    import csv
    import io

    return next(csv.reader(io.StringIO(line)))


def test_blank_repeated_header_and_total_rows_are_skipped(run, make_files):
    """M09."""
    header = PAYROLL.splitlines()[0]
    text = (
        PAYROLL
        + "\n"
        + header
        + "\n"
        + 'P-3003,"DOYLE, KATHERINE",RN,BYS,2026-09-14,2026-09-20,32\n'
        + "Total,,,,,,108\n"
        + "* excludes agency staff\n"
    )
    result = run(make_files({"a.csv": text}))
    assert "ROW_DROPPED_NONDATA" in result.codes()
    dropped = next(flag for flag in result.flags if flag.rule_code == "ROW_DROPPED_NONDATA")
    assert dropped.occurrence_count == 4
    assert len(records_of(result, "payroll")) == 3


def test_a_truncated_row_is_quarantined_and_the_rest_of_the_file_survives(run, make_files):
    """M69: visibly broken beats quietly missing."""
    text = PAYROLL + "P-3003,INCOMPLETE\n"
    result = run(make_files({"a.csv": text}))
    assert "ROW_FIELD_COUNT_MISMATCH" in result.codes()
    assert len(records_of(result, "payroll")) == 2
    assert result.quarantined_count == 1


def test_an_unrelated_file_is_refused_without_affecting_the_others(run, make_files):
    """M58: an inventory list dropped in with the real sources."""
    result = run(
        make_files(
            {
                "payroll.csv": PAYROLL,
                "roster.csv": ROSTER,
                "stock.csv": "sku,description,qty,unit_price\nA1,Gloves,400,3.20\n",
            }
        )
    )
    blockers = [flag for flag in result.flags if flag.severity is Severity.BLOCKER]
    assert [flag.rule_code for flag in blockers] == ["FILE_TYPE_UNKNOWN"]
    assert "stock.csv" in blockers[0].message
    assert records_of(result, "payroll") and records_of(result, "hr")


def test_the_same_file_twice_is_not_counted_twice(run, make_files):
    """M47."""
    result = run(make_files({"payroll.csv": PAYROLL, "payroll_copy.csv": PAYROLL}))
    assert "FILE_DUPLICATE" in result.codes()
    assert len(records_of(result, "payroll")) == 2, "one copy's worth of rows, not two"


def test_misleading_filenames_do_not_matter(run, make_files):
    """M46."""
    result = run(make_files({"schedule.pdf.csv": PAYROLL, "Book1.csv": ROSTER}))
    sources = sorted(read.detection.source for read in result.reads)
    assert sources == ["hr", "payroll"]


def test_a_preamble_above_the_header_is_skipped(run, make_files):
    text = "Harborview Care Group\nGenerated 2026-09-21\n\n" + PAYROLL
    result = run(make_files({"a.csv": text}))
    assert len(records_of(result, "payroll")) == 2
    assert not result.flags_above_info()


def test_a_type_override_turns_an_unknown_file_into_a_specific_problem(run, make_files):
    """The escape hatch the blocker's suggested action points at.

    Forcing the type does not force the contract to be satisfied, and it should not:
    the useful change is that "we have no idea what this file is" becomes "this is
    payroll, and these three columns are missing", which names the next fix.
    """
    odd = 'ref,person,duty,site,from,to,qty\n1,"X, Y",RN,BYS,2026-09-14,2026-09-20,8\n'
    refused = run(make_files({"odd.csv": odd}, "refused"))
    assert "FILE_TYPE_UNKNOWN" in refused.codes()

    forced = run(make_files({"odd.csv": odd}, "forced"), type_overrides={"odd.csv": "payroll"})
    assert "FILE_TYPE_UNKNOWN" not in forced.codes()
    missing = next(flag for flag in forced.flags if flag.rule_code == "HEADER_REQUIRED_MISSING")
    assert "employee_name" in missing.message


def test_a_type_override_reads_a_file_whose_headers_are_recognisable(run, make_files):
    """When the columns do map, the override is all that was missing."""
    text = PAYROLL.replace("payroll_id,", "internal_ref,")
    forced = run(make_files({"odd.csv": text}, "forced2"), type_overrides={"odd.csv": "payroll"})
    assert len(records_of(forced, "payroll")) == 2
    assert forced.reads[0].detection.method == "override"


# --- what ends up in the database -------------------------------------------


def test_the_run_is_recorded_with_its_files_rows_and_events(run, sample_dir):
    result = run(sample_dir / "clean")
    db = run.db

    assert db.scalar("SELECT status FROM runs WHERE run_id = ?", [result.run_id]) == "OK"
    assert db.scalar("SELECT count(*) FROM files") == 6
    assert db.scalar("SELECT count(*) FROM run_files WHERE run_id = ?", [result.run_id]) == 6
    assert db.scalar("SELECT count(*) FROM std_records WHERE run_id = ?", [result.run_id]) == 48
    assert db.scalar("SELECT count(*) FROM raw_rows WHERE run_id = ?", [result.run_id]) == 48
    assert db.scalar("SELECT count(*) FROM node_stats WHERE run_id = ?", [result.run_id]) >= 6
    assert db.scalar("SELECT count(*) FROM run_events WHERE run_id = ?", [result.run_id]) > 0


def test_detection_details_are_stored_against_the_file(run, sample_dir):
    run(sample_dir / "clean")
    rows = run.db.query(
        "SELECT original_name, detected_source, detect_confidence, encoding, delimiter "
        "FROM files WHERE media_kind = 'tabular' ORDER BY original_name"
    )
    assert {row["detected_source"] for row in rows} == {
        "census",
        "hr",
        "licenses",
        "payroll",
        "vendor_documents",
    }
    assert all(row["detect_confidence"] >= 0.5 for row in rows)
    assert all(row["encoding"] == "utf-8" for row in rows)


def test_raw_values_are_kept_beside_the_normalized_ones(run, make_files):
    """Principle 2: a flag is only useful if it can point at the characters."""
    result = run(make_files({"a.csv": PAYROLL}))
    row = run.db.query_one(
        "SELECT raw_json, norm_json FROM raw_rows WHERE run_id = ? AND row_index = 2",
        [result.run_id],
    )
    assert "REYES, SOFIA" in row["raw_json"]
    assert "employee_name" in row["norm_json"]


def test_the_standardized_views_expose_the_records(run, sample_dir):
    result = run(sample_dir / "clean")
    assert run.db.scalar("SELECT count(*) FROM std_hr WHERE run_id = ?", [result.run_id]) == 10
    assert run.db.scalar("SELECT count(*) FROM std_payroll WHERE run_id = ?", [result.run_id]) == 11
    assert (
        run.db.scalar("SELECT count(*) FROM std_licenses WHERE run_id = ?", [result.run_id]) == 10
    )


def test_a_landed_file_is_stored_under_its_own_hash(run, make_files):
    result = run(make_files({"a.csv": PAYROLL}))
    landed = result.files[0]
    assert landed.stored_path.exists()
    assert landed.sha256 in str(landed.stored_path)
    assert landed.stored_path.read_bytes() == PAYROLL.encode()
