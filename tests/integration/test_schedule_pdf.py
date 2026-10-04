"""The schedule PDF adapter against real generated pages.

The highest-variance input in the system. These run against the committed fixtures and
against pages built on the spot by the parametric generator, so the layouts the chaos
deck will mutate are exercised here first.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from sot.adapters.schedule_pdf import extract_schedule, infer_years, parse_day_header
from sot.ingest.contracts import load_pack
from sot.normalize.names import name_key

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SAMPLES = REPO_ROOT / "data" / "samples" / "healthcare"
PERIOD = [(date(2026, 9, 14), date(2026, 9, 20))]
AS_OF = date(2026, 9, 21)

sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="module")
def healthcare_pack():
    return load_pack("healthcare_ny", packs_dir=str(REPO_ROOT / "packs"))


@pytest.fixture(scope="module")
def home_facilities(healthcare_pack):
    crosswalk = healthcare_pack.crosswalk("facilities")
    table = {}
    with open(SAMPLES / "clean" / "roster_export.csv", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = name_key(f"{row['first_name']} {row['last_name']}")
            table[key] = crosswalk.resolve(row["facility"])
    return table


def run(data: bytes, healthcare_pack, home_facilities=None, **kwargs):
    return extract_schedule(
        data,
        file_id="FL-test",
        as_of=kwargs.pop("as_of", AS_OF),
        facilities=healthcare_pack.crosswalk("facilities"),
        roles=healthcare_pack.crosswalk("roles"),
        shift_codes=healthcare_pack.setting("shift_codes"),
        period_hints=kwargs.pop("period_hints", PERIOD),
        home_facility_by_key=home_facilities or {},
        **kwargs,
    )


def build_pdf(tmp_path: Path, pages, **options) -> bytes:
    from make_schedule_pdf import PdfOptions, write_schedule_pdf

    path = write_schedule_pdf(tmp_path / "built.pdf", pages, PdfOptions(**options))
    return path.read_bytes()


def sample_pages(**overrides):
    import generate_samples as gen

    pages = gen.build_schedule_pages(gen.build_people(), gen.CLEAN_SCHEDULE, **overrides)
    return pages


# --- the clean fixture ------------------------------------------------------


def test_the_clean_schedule_parses_to_exactly_the_expected_hours(healthcare_pack, home_facilities):
    """Phase 3's exit criterion. These totals are what payroll is reconciled against,
    so an error here is an error in every downstream number."""
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )

    hours: dict[str, float] = {}
    for segment in result.segments:
        hours[segment["person_ref"]] = round(
            hours.get(segment["person_ref"], 0) + (segment["hours"] or 0), 2
        )

    assert hours == {
        "Sofia Reyes": 36.0,
        "Kate Doyle": 32.0,
        "José Peña": 40.0,
        "Ana García-López": 40.0,
        "Kevin O'Brien": 40.0,
        "Priya Nair": 32.0,
        "Marc Bell": 40.0,
        "Robert Hayes Jr.": 32.0,
        "Daniel Okafor": 40.0,
        "Astrid Lindqvist": 40.0,
    }


def test_the_clean_schedule_raises_nothing_but_the_float(healthcare_pack, home_facilities):
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    assert result.codes() == ["PERSON_ON_MULTIPLE_PAGES"]


def test_each_page_is_matched_to_its_facility_from_the_title(healthcare_pack, home_facilities):
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    assert [(page.facility_code, page.facility_source) for page in result.pages] == [
        ("BYS", "title"),
        ("RVD", "title"),
    ]


def test_the_year_is_inferred_from_the_payroll_periods(healthcare_pack, home_facilities):
    """The printed page carries no year at all, exactly as in the brief."""
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    dates = {segment["work_date"] for segment in result.segments}
    assert min(dates) == date(2026, 9, 14)
    assert max(dates) == date(2026, 9, 20)


def test_the_ruled_grid_is_used_and_every_cell_keeps_its_position(healthcare_pack, home_facilities):
    """Without geometry the evidence viewer cannot point at anything."""
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    assert all(page.method == "lines" for page in result.pages)
    assert result.cells
    assert all(cell["x0"] is not None and cell["top"] is not None for cell in result.cells)
    assert all(cell["confidence"] == 1.0 for cell in result.cells)


def test_the_footnote_is_read_from_each_page(healthcare_pack, home_facilities):
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    assert all(len(page.footnote.by_times) == 4 for page in result.pages)
    assert all(
        segment["hours_source"] == "footnote"
        for segment in result.segments
        if segment["category"] == "WORK"
    )


def test_the_float_appears_on_both_pages_with_the_right_site_on_each(
    healthcare_pack, home_facilities
):
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    by_site: dict[str, float] = {}
    for segment in result.segments:
        if segment["person_ref"] == "Priya Nair":
            by_site[segment["facility_code"]] = round(
                by_site.get(segment["facility_code"], 0) + segment["hours"], 2
            )
    assert by_site == {"RVD": 24.0, "BYS": 8.0}


def test_roles_are_resolved_to_canonical_codes(healthcare_pack, home_facilities):
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    assert {segment["role_code"] for segment in result.segments} == {"RN", "LPN", "CNA"}


# --- the messy fixture ------------------------------------------------------


def test_the_messy_schedule_finds_every_planted_problem(healthcare_pack, home_facilities):
    result = run(
        (SAMPLES / "messy" / "schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    codes = set(result.codes())
    assert {"PTO_ON_SCHEDULE", "SHIFT_NOT_IN_FOOTNOTE", "SHIFT_SPANS_PERIOD"} <= codes


def test_an_overnight_shift_is_recorded_with_timestamps_crossing_midnight(
    healthcare_pack, home_facilities
):
    result = run(
        (SAMPLES / "messy" / "schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    overnight = [
        segment
        for segment in result.segments
        if segment["start_ts"]
        and segment["end_ts"]
        and segment["end_ts"].date() > segment["start_ts"].date()
    ]
    assert overnight, "the planted 11p-7a should cross midnight"


def test_paid_leave_is_given_the_persons_usual_shift_length(healthcare_pack, home_facilities):
    """The cell says PTO, not how long. The person's own usual shift is the best
    available answer, and the assumption is recorded on the segment."""
    result = run(
        (SAMPLES / "messy" / "schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    pto = [segment for segment in result.segments if segment["category"] == "PTO"]
    assert len(pto) == 1
    assert pto[0]["hours"] == 8.0
    assert pto[0]["hours_source"] == "assumed"
    assert "assumed" in (pto[0]["note"] or "")


def test_an_agency_nurse_on_the_page_still_produces_segments(healthcare_pack, home_facilities):
    """Unknown to every other system, but visibly on the rota. Dropping them would
    hide the staffing they provided."""
    result = run(
        (SAMPLES / "messy" / "schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    assert any(segment["person_ref"] == "L. Okonkwo" for segment in result.segments)


# --- the scanned fixture ----------------------------------------------------


def test_a_scanned_page_blocks_itself_without_crashing(healthcare_pack):
    """M45."""
    result = run((SAMPLES / "scan" / "scanned_schedule.pdf").read_bytes(), healthcare_pack)
    assert result.codes() == ["PDF_NO_TEXT_LAYER"]
    assert result.segments == []
    assert all(not page.readable for page in result.pages)


# --- generated variations ---------------------------------------------------


def test_en_dashes_and_mixed_case_read_identically(tmp_path, healthcare_pack, home_facilities):
    """M34."""
    pages = sample_pages()
    plain = run(build_pdf(tmp_path, pages), healthcare_pack, home_facilities)
    fancy = run(build_pdf(tmp_path, pages, dash=chr(0x2013)), healthcare_pack, home_facilities)
    assert [segment["hours"] for segment in plain.segments] == [
        segment["hours"] for segment in fancy.segments
    ]


def test_a_missing_footnote_falls_back_to_the_clock(tmp_path, healthcare_pack, home_facilities):
    """M39."""
    result = run(build_pdf(tmp_path, sample_pages(footnote=None)), healthcare_pack, home_facilities)
    assert "PDF_FOOTNOTE_MISSING" in result.codes()
    assert all(
        segment["hours_source"] == "clock"
        for segment in result.segments
        if segment["category"] == "WORK"
    )


def test_a_table_spilling_onto_a_second_page_keeps_every_row(
    tmp_path, healthcare_pack, home_facilities
):
    """M44: the continuation page has no title, and must inherit the facility."""
    whole = run(build_pdf(tmp_path, sample_pages()), healthcare_pack, home_facilities)
    split = run(
        build_pdf(tmp_path, sample_pages(), rows_per_page=3), healthcare_pack, home_facilities
    )
    assert len(split.pages) > len(whole.pages)
    assert len(split.segments) == len(whole.segments)
    assert {page.facility_code for page in split.pages} == {"BYS", "RVD"}
    assert "carried" in {page.facility_source for page in split.pages}


def test_a_page_with_no_grid_lines_is_rebuilt_from_word_positions(
    tmp_path, healthcare_pack, home_facilities
):
    """The fallback that matters most against a file we have not seen."""
    result = run(
        build_pdf(tmp_path, sample_pages(), draw_grid=False), healthcare_pack, home_facilities
    )
    assert result.segments
    assert all(page.readable for page in result.pages)


def test_a_notes_page_blocks_only_itself(tmp_path, healthcare_pack, home_facilities):
    """M67."""
    from make_schedule_pdf import SchedulePage

    pages = [
        *sample_pages(),
        SchedulePage(
            facility_label="Notice",
            week_label="",
            day_headers=(),
            body_text="Flu vaccinations are available at the nurses' station all week.",
        ),
    ]
    result = run(build_pdf(tmp_path, pages), healthcare_pack, home_facilities)
    assert "PDF_TABLE_NOT_FOUND" in result.codes()
    assert len(result.segments) == 46, "the real pages are untouched"


def test_a_page_with_no_recognisable_facility_is_inferred_from_its_staff(
    tmp_path, healthcare_pack, home_facilities
):
    """M66."""
    from dataclasses import replace

    pages = [replace(page, facility_label="Weekly Rota") for page in sample_pages()]
    result = run(build_pdf(tmp_path, pages), healthcare_pack, home_facilities)
    assert "PDF_FACILITY_UNKNOWN" in result.codes()
    assert {page.facility_code for page in result.pages} == {"BYS", "RVD"}
    assert all(page.facility_source == "inferred" for page in result.pages)


def test_without_a_roster_an_unnamed_page_blocks_itself(tmp_path, healthcare_pack):
    """Neither the title nor the staff identify it, so nothing from it is used."""
    from dataclasses import replace

    pages = [replace(page, facility_label="Weekly Rota") for page in sample_pages()]
    result = run(build_pdf(tmp_path, pages), healthcare_pack, home_facilities=None)
    assert "PDF_FACILITY_UNKNOWN" in result.codes()
    assert result.segments == []


# --- day headers and years --------------------------------------------------


@pytest.mark.parametrize(
    ("header", "month", "day"),
    [
        ("Mon 09/14", 9, 14),
        ("Monday 9/14", 9, 14),
        ("9/14 Mon", 9, 14),
        ("09/14/2026", 9, 14),
        ("Tue 9-15", 9, 15),
        ("Wed 09.16", 9, 16),
    ],
)
def test_day_headings_are_read_in_every_form(header: str, month: int, day: int):
    column = parse_day_header(header, 0)
    assert (column.month, column.day) == (month, day)


def test_a_bare_weekday_is_still_a_day_column():
    assert parse_day_header("Thursday", 0) is not None


def test_a_label_column_is_not_a_day_column():
    assert parse_day_header("Staff", 0) is None
    assert parse_day_header("Role", 1) is None


def test_a_year_printed_on_the_page_wins():
    columns = [parse_day_header(f"09/{day:02d}/2024", index) for index, day in enumerate((14, 15))]
    resolved, basis = infer_years(columns, as_of=AS_OF)
    assert resolved[0].work_date == date(2024, 9, 14)
    assert "printed on the page" in basis


def test_payroll_periods_resolve_the_year_when_the_page_does_not():
    columns = [parse_day_header(f"Mon 09/{day}", index) for index, day in enumerate((14, 15))]
    resolved, basis = infer_years(columns, as_of=date(2027, 3, 1), period_hints=PERIOD)
    assert resolved[0].work_date == date(2026, 9, 14)
    assert "payroll periods" in basis


def test_the_nearest_year_is_used_when_nothing_else_is_known():
    columns = [parse_day_header("Mon 09/14", 0)]
    resolved, basis = infer_years(columns, as_of=AS_OF)
    assert resolved[0].work_date == date(2026, 9, 14)
    assert "closest to the as-of date" in basis


def test_a_week_crossing_new_year_gets_both_years():
    """M43."""
    headers = ["Mon 12/28", "Tue 12/29", "Wed 12/30", "Thu 12/31", "Fri 01/01", "Sat 01/02"]
    columns = [parse_day_header(header, index) for index, header in enumerate(headers)]
    resolved, _ = infer_years(columns, as_of=date(2026, 1, 5))
    assert resolved[0].work_date.year == 2025
    assert resolved[4].work_date == date(2026, 1, 1)


def test_a_weekday_that_does_not_match_its_date_is_flagged_and_the_date_trusted(
    tmp_path, healthcare_pack, home_facilities
):
    """M42."""
    from dataclasses import replace

    pages = sample_pages()
    broken = ("Fri 09/14", *pages[0].day_headers[1:])
    result = run(
        build_pdf(tmp_path, [replace(pages[0], day_headers=broken), pages[1]]),
        healthcare_pack,
        home_facilities,
    )
    assert "PDF_FACILITY_UNKNOWN" not in result.codes()
    assert "WEEKDAY_DATE_MISMATCH" in result.codes()
    monday = [segment for segment in result.segments if segment["work_date"] == date(2026, 9, 14)]
    assert monday, "the date is trusted over the weekday"


def test_segments_carry_timestamps_and_their_place_on_the_page(healthcare_pack, home_facilities):
    result = run(
        (SAMPLES / "clean" / "weekly_schedule.pdf").read_bytes(), healthcare_pack, home_facilities
    )
    segment = next(s for s in result.segments if s["category"] == "WORK")
    assert isinstance(segment["start_ts"], datetime)
    assert segment["page"] >= 1
    assert segment["column_header"].startswith(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    assert segment["segment_id"].startswith("SG-")
