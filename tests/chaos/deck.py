"""The chaos deck.

Each mutation breaks the clean sample in one specific way and says two things: what
the engine must notice, and what it must *not* say. The second half is the half that
catches over-reaction - renaming a column header should change nothing at all, and a
system that panics about it is as useless as one that misses a ghost employee.

Mutations are applied to a copy of the clean set, so the baseline is never touched and
every mutation is independent of every other.
"""

from __future__ import annotations

import csv
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

CLEAN = REPO_ROOT / "data" / "samples" / "healthcare" / "clean"

ROSTER = "roster_export.csv"
PAYROLL = "pay_register_2026-09-20.csv"
LICENSES = "license_verification.csv"
CENSUS = "census.csv"
SCHEDULE = "weekly_schedule.pdf"


@dataclass(frozen=True)
class Mutation:
    """One deliberate break, and what the engine should make of it."""

    id: str
    description: str
    apply: Callable[[Path], None]
    expect_codes: tuple[str, ...] = ()
    forbid_codes: tuple[str, ...] = ()
    #: Some findings only exist relative to a particular day. A shift is "worked" or
    #: "still to come" depending on where the as-of date falls, and the forecast half
    #: cannot be reached from a date after the whole week.
    as_of: date | None = None
    note: str = ""


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return (rows[0], rows[1:])


def write_rows(path: Path, header: list[str], rows: list[list[str]], **kwargs) -> None:
    newline = kwargs.pop("lineterminator", "\n")
    encoding = kwargs.pop("encoding", "utf-8")
    with open(path, "w", newline="", encoding=encoding) as handle:
        writer = csv.writer(handle, lineterminator=newline)
        writer.writerow(header)
        writer.writerows(rows)


def edit(path: Path, row_index: int, column: str, value: str) -> None:
    """Change one cell, by column name."""
    header, rows = read_rows(path)
    rows[row_index][header.index(column)] = value
    write_rows(path, header, rows)


def rebuild_schedule(target: Path, **options) -> None:
    """Regenerate the rota PDF with different options or contents."""
    import generate_samples as gen
    from make_schedule_pdf import PdfOptions, write_schedule_pdf

    page_kwargs = {}
    if "footnote" in options:
        page_kwargs["footnote"] = options.pop("footnote")
    extra_rows = options.pop("extra_rows", None)
    if extra_rows:
        page_kwargs["extra_rows"] = extra_rows
    schedule = options.pop("schedule", gen.CLEAN_SCHEDULE)
    people = options.pop("people", gen.build_people())
    pages = options.pop("pages", None) or gen.build_schedule_pages(people, schedule, **page_kwargs)
    write_schedule_pdf(target / SCHEDULE, pages, PdfOptions(**options))


# ---------------------------------------------------------------------------
# The deck
# ---------------------------------------------------------------------------


def _rename_headers(target: Path) -> None:
    _, rows = read_rows(target / PAYROLL)
    renamed = [
        "Pay ID",
        "Employee",
        "Position Code",
        "Cost Centre",
        "Week Start",
        "Week End",
        "Hrs",
    ]
    write_rows(target / PAYROLL, renamed, rows)


def _reorder_columns(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    order = [6, 0, 5, 1, 4, 2, 3]
    write_rows(
        target / PAYROLL,
        [header[i] for i in order],
        [[row[i] for i in order] for row in rows],
    )


def _extra_column(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    write_rows(target / PAYROLL, [*header, "union_local"], [[*row, "L1199"] for row in rows])


def _drop_hours_column(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    index = header.index("hours_paid")
    write_rows(
        target / PAYROLL,
        [cell for i, cell in enumerate(header) if i != index],
        [[cell for i, cell in enumerate(row) if i != index] for row in rows],
    )


def _unquoted_name(target: Path) -> None:
    text = (target / PAYROLL).read_text(encoding="utf-8")
    first = text.splitlines()[1]
    (target / PAYROLL).write_text(text.replace(first, first.replace('"', ""), 1), encoding="utf-8")


def _bom_and_crlf(target: Path) -> None:
    text = (target / PAYROLL).read_text(encoding="utf-8")
    (target / PAYROLL).write_bytes(text.replace("\n", "\r\n").encode("utf-8-sig"))


def _latin1(target: Path) -> None:
    text = (target / ROSTER).read_text(encoding="utf-8")
    (target / ROSTER).write_bytes(text.encode("cp1252"))


def _tab_delimited(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    with open(target / PAYROLL, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _junk_rows(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    total = ["Total", "", "", "", "", "", "392"]
    write_rows(
        target / PAYROLL,
        header,
        [*rows, [], header, total, ["* excludes agency", "", "", "", "", "", ""]],
    )


def _unrelated_file(target: Path) -> None:
    (target / "inventory.csv").write_text(
        "sku,description,qty,unit_price\nA1,Gloves,400,3.20\nB2,Wipes,120,1.80\n",
        encoding="utf-8",
    )


def _truncated_row(target: Path) -> None:
    with open(target / PAYROLL, "a", encoding="utf-8") as handle:
        handle.write("P-9999,INCOMPLETE\n")


def _duplicate_file(target: Path) -> None:
    shutil.copy(target / PAYROLL, target / "payroll_copy.csv")


def _misleading_names(target: Path) -> None:
    (target / PAYROLL).rename(target / "Book1.csv")
    (target / ROSTER).rename(target / "schedule_FINAL.csv")


def _excel_serials(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    index = header.index("hire_date")
    from datetime import date as date_type

    epoch = date_type(1899, 12, 30)
    for row in rows:
        row[index] = str((date_type.fromisoformat(row[index]) - epoch).days)
    write_rows(target / ROSTER, header, rows)


def _ambiguous_dates(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    index = header.index("hire_date")
    from datetime import date as date_type

    for row in rows:
        parsed = date_type.fromisoformat(row[index])
        row[index] = f"{parsed.month}/{parsed.day}/{parsed.year}"
    rows[0][index] = "3/4/2020"
    write_rows(target / ROSTER, header, rows)


def _impossible_date(target: Path) -> None:
    edit(target / ROSTER, 0, "hire_date", "2020-02-30")


def _unparseable_date(target: Path) -> None:
    edit(target / ROSTER, 0, "hire_date", "spring 2020")


def _bad_phone(target: Path) -> None:
    edit(target / ROSTER, 0, "phone", "018-555-0201")


def _license_variants(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    index = header.index("license_number")
    rows[0][index] = rows[0][index].replace("-", "").lower()
    write_rows(target / ROSTER, header, rows)


def _prefix_mismatch(target: Path) -> None:
    header, rows = read_rows(target / LICENSES)
    number = header.index("license_number")
    kind = header.index("license_type")
    for row in rows:
        if row[kind] == "RN":
            row[number] = row[number].replace("RN-", "CNA-")
            break
    write_rows(target / LICENSES, header, rows)


def _hours_variants(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    index = header.index("hours_paid")
    rows[0][index] = "36:00"
    rows[1][index] = "32 hrs"
    rows[2][index] = "-4"
    rows[3][index] = "200"
    write_rows(target / PAYROLL, header, rows)


def _unparseable_hours(target: Path) -> None:
    edit(target / PAYROLL, 0, "hours_paid", "forty")


def _unknown_facility(target: Path) -> None:
    edit(target / PAYROLL, 0, "facility_code", "HVB")


def _unknown_role(target: Path) -> None:
    edit(target / PAYROLL, 0, "job_code", "FLT")


def _ghost_payroll(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    write_rows(
        target / PAYROLL,
        header,
        [*rows, ["P-9001", "TORRES, MIGUEL", "CNA", "RVD", "2026-09-14", "2026-09-20", "32"]],
    )


def _duplicate_pay_row(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    copy = list(rows[0])
    copy[0] = "P-9002"
    write_rows(target / PAYROLL, header, [*rows, copy])


def _shared_license(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    index = header.index("license_number")
    rows[1][index] = rows[0][index]
    write_rows(target / ROSTER, header, rows)


def _employee_id_collision(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    rows[1][header.index("employee_id")] = rows[0][header.index("employee_id")]
    write_rows(target / ROSTER, header, rows)


def _rehire_duplicate(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    copy = list(rows[0])
    copy[header.index("employee_id")] = "E999"
    write_rows(target / ROSTER, header, [*rows, copy])


def _license_not_in_service(target: Path) -> None:
    header, rows = read_rows(target / LICENSES)
    write_rows(target / LICENSES, header, rows[1:])


def _no_credential_for_nurse(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    number = header.index("license_number")
    target_number = rows[0][number]
    rows[0][number] = ""
    write_rows(target / ROSTER, header, rows)
    header, licence_rows = read_rows(target / LICENSES)
    write_rows(
        target / LICENSES,
        header,
        [row for row in licence_rows if row[header.index("license_number")] != target_number],
    )


def _maiden_name(target: Path) -> None:
    header, rows = read_rows(target / LICENSES)
    index = header.index("name_on_license")
    rows[0][index] = "ABERNATHY, MARCUS"
    write_rows(target / LICENSES, header, rows)


def _orphan_license(target: Path) -> None:
    header, rows = read_rows(target / LICENSES)
    write_rows(
        target / LICENSES,
        header,
        [*rows, ["RN-999999", "FORMER, STAFFER", "RN", "2027-01-31", "2026-09-01"]],
    )


def _hours_variance(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    rows[0][header.index("hours_paid")] = "48"
    rows[1][header.index("hours_paid")] = "20"
    write_rows(target / PAYROLL, header, rows)


def _facility_conflict(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    for row in rows:
        if row[header.index("facility_code")] == "BYS":
            row[header.index("facility_code")] = "RVD"
            break
    write_rows(target / PAYROLL, header, rows)


def _role_conflict(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    for row in rows:
        if row[header.index("job_code")] == "RN":
            row[header.index("job_code")] = "LPN"
            break
    write_rows(target / PAYROLL, header, rows)


def _role_exceeds_license(target: Path) -> None:
    header, rows = read_rows(target / ROSTER)
    for row in rows:
        if row[header.index("job_title")] == "Certified Nursing Assistant":
            row[header.index("job_title")] = "Registered Nurse"
            break
    write_rows(target / ROSTER, header, rows)


def _hr_expiry_stale(target: Path) -> None:
    edit(target / ROSTER, 0, "license_expiration", "2030-01-31")


def _stale_verification(target: Path) -> None:
    edit(target / LICENSES, 0, "last_verified", "2025-01-15")


def _expired_with_shifts(target: Path) -> None:
    edit(target / LICENSES, 0, "expiration_date", "2026-09-15")
    edit(target / ROSTER, 1, "license_expiration", "2026-09-15")


def _expiring_soon(target: Path) -> None:
    header, rows = read_rows(target / LICENSES)
    rows[0][header.index("expiration_date")] = "2026-11-05"
    rows[1][header.index("expiration_date")] = "2026-10-01"
    write_rows(target / LICENSES, header, rows)


def _expiry_mid_week(target: Path) -> None:
    """A credential lapsing part way through the week, judged from inside it."""
    edit(target / LICENSES, 0, "expiration_date", "2026-09-17")
    edit(target / ROSTER, 1, "license_expiration", "2026-09-17")


def _hire_after_period(target: Path) -> None:
    edit(target / ROSTER, 0, "hire_date", "2026-09-25")


def _different_weeks(target: Path) -> None:
    header, rows = read_rows(target / PAYROLL)
    for row in rows:
        row[header.index("period_start")] = "2026-10-05"
        row[header.index("period_end")] = "2026-10-11"
    write_rows(target / PAYROLL, header, rows)


def _short_period(target: Path) -> None:
    edit(target / PAYROLL, 0, "period_end", "2026-09-19")


def _no_rn_day(target: Path) -> None:
    import generate_samples as gen

    schedule = dict(gen.CLEAN_SCHEDULE)
    schedule[("RVD", "E207")] = ("OFF", "OFF", "OFF", "7a-3p", "7a-3p", "7a-3p", "OFF")
    schedule[("RVD", "E208")] = ("7a-3p", "7a-3p", "7a-3p", "OFF", "OFF", "OFF", "OFF")
    rebuild_schedule(target, schedule=schedule)


def _en_dashes(target: Path) -> None:
    rebuild_schedule(target, dash=chr(0x2013))


def _no_footnote(target: Path) -> None:
    rebuild_schedule(target, footnote=None)


def _unparseable_cell(target: Path) -> None:
    import generate_samples as gen

    schedule = dict(gen.CLEAN_SCHEDULE)
    week = list(schedule[("BYS", "E201")])
    week[2] = "lunch cover"
    schedule[("BYS", "E201")] = tuple(week)
    rebuild_schedule(target, schedule=schedule)


def _pto_cell(target: Path) -> None:
    import generate_samples as gen

    schedule = dict(gen.CLEAN_SCHEDULE)
    week = list(schedule[("BYS", "E205")])
    week[3] = "PTO"
    schedule[("BYS", "E205")] = tuple(week)
    rebuild_schedule(target, schedule=schedule)


def _undefined_shift(target: Path) -> None:
    import generate_samples as gen

    schedule = dict(gen.CLEAN_SCHEDULE)
    week = list(schedule[("BYS", "E206")])
    week[6] = "7p-7a"
    schedule[("BYS", "E206")] = tuple(week)
    rebuild_schedule(target, schedule=schedule)


def _overlapping_shifts(target: Path) -> None:
    import generate_samples as gen

    schedule = dict(gen.CLEAN_SCHEDULE)
    schedule[("BYS", "E208")] = ("7a-3p", "OFF", "OFF", "7a-3p", "OFF", "OFF", "OFF")
    rebuild_schedule(target, schedule=schedule)


def _over_daily_cap(target: Path) -> None:
    import generate_samples as gen

    schedule = dict(gen.CLEAN_SCHEDULE)
    # Two twelves is 24 hours, over the cap, and short enough to fit the column.
    schedule[("BYS", "E201")] = ("7a-7p/7p-7a", "7a-3p", "OFF", "7a-7p", "OFF", "7a-3p", "OFF")
    rebuild_schedule(target, schedule=schedule)


def _weekday_mismatch(target: Path) -> None:
    from dataclasses import replace

    import generate_samples as gen

    pages = gen.build_schedule_pages(gen.build_people(), gen.CLEAN_SCHEDULE)
    broken = ("Fri 09/14", *pages[0].day_headers[1:])
    rebuild_schedule(target, pages=[replace(pages[0], day_headers=broken), pages[1]])


def _notes_page(target: Path) -> None:
    import generate_samples as gen
    from make_schedule_pdf import SchedulePage

    pages = gen.build_schedule_pages(gen.build_people(), gen.CLEAN_SCHEDULE)
    pages.append(
        SchedulePage(
            facility_label="Notice",
            week_label="",
            day_headers=(),
            body_text="Flu vaccinations at the nurses' station all week.",
        )
    )
    rebuild_schedule(target, pages=pages)


def _unnamed_facility(target: Path) -> None:
    from dataclasses import replace

    import generate_samples as gen

    pages = gen.build_schedule_pages(gen.build_people(), gen.CLEAN_SCHEDULE)
    rebuild_schedule(target, pages=[replace(page, facility_label="Weekly Rota") for page in pages])


def _split_pages(target: Path) -> None:
    rebuild_schedule(target, rows_per_page=3)


def _no_grid(target: Path) -> None:
    rebuild_schedule(target, draw_grid=False)


def _scanned(target: Path) -> None:
    from make_schedule_pdf import rasterize_pdf

    rasterize_pdf(target / SCHEDULE, target / SCHEDULE)


def _big_census(target: Path) -> None:
    header, rows = read_rows(target / CENSUS)
    for row in rows:
        row[header.index("residents")] = "40"
    write_rows(target / CENSUS, header, rows)


def _aide_expiry_mid_month(target: Path) -> None:
    header, rows = read_rows(target / LICENSES)
    for row in rows:
        if row[header.index("license_type")] == "CNA":
            row[header.index("expiration_date")] = "2027-04-15"
            break
    write_rows(target / LICENSES, header, rows)


def _kitchen_sink(target: Path) -> None:
    _ghost_payroll(target)
    _unknown_facility(target)
    _stale_verification(target)
    _junk_rows(target)
    _unrelated_file(target)
    _no_rn_day(target)
    _duplicate_file(target)


DECK: list[Mutation] = [
    # --- CSV structure ---------------------------------------------------
    Mutation(
        "M01",
        "Headers renamed to synonyms",
        _rename_headers,
        forbid_codes=("FILE_TYPE_UNKNOWN", "HEADER_REQUIRED_MISSING"),
    ),
    Mutation(
        "M02",
        "Columns reordered",
        _reorder_columns,
        forbid_codes=("FILE_TYPE_UNKNOWN", "HEADER_REQUIRED_MISSING"),
    ),
    Mutation(
        "M03",
        "An extra column nobody knows",
        _extra_column,
        expect_codes=("HEADER_UNMAPPED_COLUMN",),
    ),
    Mutation(
        "M04",
        "Payroll loses its hours column",
        _drop_hours_column,
        expect_codes=("HEADER_REQUIRED_MISSING", "SOURCE_MISSING"),
    ),
    Mutation(
        "M05",
        "A name written without its quotes",
        _unquoted_name,
        expect_codes=("ROW_DELIMITER_REPAIRED",),
    ),
    Mutation(
        "M06",
        "Byte-order mark and Windows line endings",
        _bom_and_crlf,
        forbid_codes=("ENCODING_FALLBACK", "ROW_FIELD_COUNT_MISMATCH"),
    ),
    Mutation(
        "M07", "Latin-1 file with accented names", _latin1, expect_codes=("ENCODING_FALLBACK",)
    ),
    Mutation(
        "M08",
        "Tab delimited",
        _tab_delimited,
        forbid_codes=("FILE_TYPE_UNKNOWN", "ROW_FIELD_COUNT_MISMATCH"),
    ),
    Mutation(
        "M09",
        "Blank, repeated header, total and notes rows",
        _junk_rows,
        expect_codes=("ROW_DROPPED_NONDATA",),
    ),
    Mutation(
        "M58",
        "An unrelated inventory file dropped in",
        _unrelated_file,
        expect_codes=("FILE_TYPE_UNKNOWN",),
        forbid_codes=("HEADER_REQUIRED_MISSING",),
    ),
    Mutation("M69", "A truncated row", _truncated_row, expect_codes=("ROW_FIELD_COUNT_MISMATCH",)),
    Mutation(
        "M47", "The same file uploaded twice", _duplicate_file, expect_codes=("FILE_DUPLICATE",)
    ),
    Mutation("M46", "Misleading filenames", _misleading_names, forbid_codes=("FILE_TYPE_UNKNOWN",)),
    # --- Values ----------------------------------------------------------
    Mutation(
        "M10",
        "Dates exported as spreadsheet serials",
        _excel_serials,
        expect_codes=("EXCEL_SERIAL_DATE",),
    ),
    Mutation(
        "M11",
        "Ambiguous day/month order",
        _ambiguous_dates,
        expect_codes=("DATE_AMBIGUOUS_ASSUMED",),
    ),
    Mutation(
        "M12", "A date that does not exist", _impossible_date, expect_codes=("DATE_IMPOSSIBLE",)
    ),
    Mutation(
        "M57", "Free text in a date column", _unparseable_date, expect_codes=("DATE_UNPARSEABLE",)
    ),
    Mutation("M13", "An unusable phone number", _bad_phone, expect_codes=("PHONE_INVALID",)),
    Mutation(
        "M14",
        "Credential number without its prefix or case",
        _license_variants,
        forbid_codes=("LICENSE_NOT_IN_SERVICE", "UNMATCHED_LICENSE"),
    ),
    Mutation(
        "M15",
        "Credential prefix contradicts its type",
        _prefix_mismatch,
        expect_codes=("LICENSE_PREFIX_TYPE_MISMATCH",),
    ),
    Mutation(
        "M16",
        "Hours as 36:00, 32 hrs, negative and 200",
        _hours_variants,
        expect_codes=("HOURS_NEGATIVE", "HOURS_EXCESSIVE_WEEK"),
    ),
    Mutation(
        "M59", "Hours written as a word", _unparseable_hours, expect_codes=("HOURS_UNPARSEABLE",)
    ),
    Mutation(
        "M52",
        "A facility code in no crosswalk",
        _unknown_facility,
        expect_codes=("CODE_UNKNOWN_FACILITY",),
    ),
    Mutation(
        "M53", "A job code in no crosswalk", _unknown_role, expect_codes=("CODE_UNKNOWN_ROLE",)
    ),
    # --- Identity ---------------------------------------------------------
    Mutation(
        "M20", "Paid, and in no other system", _ghost_payroll, expect_codes=("UNMATCHED_PAYROLL",)
    ),
    Mutation(
        "M22",
        "The same pay period twice",
        _duplicate_pay_row,
        expect_codes=("DUPLICATE_PAY_PERIOD",),
    ),
    Mutation(
        "M30",
        "One credential number on two people",
        _shared_license,
        expect_codes=("LICENSE_NUMBER_SHARED",),
    ),
    Mutation(
        "M31",
        "One employee number on two people",
        _employee_id_collision,
        expect_codes=("EMPLOYEE_ID_COLLISION",),
    ),
    Mutation(
        "M32",
        "A rehire under a second number",
        _rehire_duplicate,
        expect_codes=("DUPLICATE_PERSON_HR",),
    ),
    Mutation(
        "M51",
        "HR lists a credential the service does not have",
        _license_not_in_service,
        expect_codes=("LICENSE_NOT_IN_SERVICE",),
    ),
    Mutation(
        "M60",
        "A nurse with no credential anywhere",
        _no_credential_for_nurse,
        expect_codes=("LICENSED_ROLE_NO_CREDENTIAL",),
    ),
    Mutation(
        "M62",
        "A credential under a previous surname",
        _maiden_name,
        expect_codes=("NAME_MISMATCH_LICENSE",),
        forbid_codes=("UNMATCHED_LICENSE",),
    ),
    Mutation(
        "M71",
        "A credential belonging to a former employee",
        _orphan_license,
        expect_codes=("UNMATCHED_LICENSE",),
    ),
    # --- Cross-source and time -------------------------------------------
    Mutation(
        "M23",
        "Paid more and paid less than rostered",
        _hours_variance,
        expect_codes=("HOURS_VARIANCE",),
    ),
    Mutation(
        "M24",
        "Paid at a site they were not rostered at",
        _facility_conflict,
        expect_codes=("FACILITY_CONFLICT",),
    ),
    Mutation(
        "M68", "Paid under a different role code", _role_conflict, expect_codes=("ROLE_CONFLICT",)
    ),
    Mutation(
        "M25",
        "An aide listed as a nurse",
        _role_exceeds_license,
        expect_codes=("ROLE_EXCEEDS_LICENSE",),
    ),
    Mutation(
        "M26",
        "HR's expiry disagrees with the service",
        _hr_expiry_stale,
        expect_codes=("HR_LICENSE_EXPIRY_STALE",),
    ),
    Mutation(
        "M29",
        "A verification over a year old",
        _stale_verification,
        expect_codes=("VERIFICATION_STALE",),
    ),
    Mutation(
        "M27",
        "A credential that expired mid-week, with shifts after it",
        _expired_with_shifts,
        expect_codes=("CREDENTIAL_EXPIRED", "WORKED_AFTER_EXPIRY"),
    ),
    Mutation(
        "M56",
        "Credentials expiring in 45 and 10 days",
        _expiring_soon,
        expect_codes=("CREDENTIAL_EXPIRING",),
    ),
    Mutation(
        "M28",
        "A credential lapsing mid-week, seen from inside the week",
        _expiry_mid_week,
        expect_codes=("SCHEDULED_AFTER_EXPIRY",),
        as_of=date(2026, 9, 16),
        note="Judged from inside the week so the later shifts are still to come.",
    ),
    Mutation(
        "M33",
        "Hired after the pay period",
        _hire_after_period,
        expect_codes=("ACTIVITY_BEFORE_HIRE",),
    ),
    Mutation(
        "M54",
        "Payroll covers a different week from the rota",
        _different_weeks,
        expect_codes=("COVERAGE_GAP_BETWEEN_SOURCES",),
        forbid_codes=("SCHEDULED_NOT_PAID", "PAID_NOT_SCHEDULED"),
    ),
    Mutation(
        "M64", "A six-day pay period", _short_period, expect_codes=("PAYROLL_PERIOD_INVALID",)
    ),
    # --- The schedule PDF -------------------------------------------------
    Mutation("M40", "A day with no RN at all", _no_rn_day, expect_codes=("RN_8H_COVERAGE_GAP",)),
    Mutation(
        "M34",
        "En dashes between shift times",
        _en_dashes,
        forbid_codes=("SHIFT_UNPARSEABLE", "PDF_TABLE_NOT_FOUND"),
    ),
    Mutation(
        "M39",
        "No shift-length note on the page",
        _no_footnote,
        expect_codes=("PDF_FOOTNOTE_MISSING",),
    ),
    Mutation(
        "M36", "A cell nobody can read", _unparseable_cell, expect_codes=("SHIFT_UNPARSEABLE",)
    ),
    Mutation("M37", "Paid leave on the rota", _pto_cell, expect_codes=("PTO_ON_SCHEDULE",)),
    Mutation(
        "M35",
        "A shift the footnote does not define",
        _undefined_shift,
        expect_codes=("SHIFT_NOT_IN_FOOTNOTE",),
    ),
    Mutation(
        "M41",
        "The same person at two sites at once",
        _overlapping_shifts,
        expect_codes=("OVERLAPPING_SHIFTS",),
    ),
    Mutation(
        "M49",
        "More hours in a day than reporting allows",
        _over_daily_cap,
        expect_codes=("DAILY_HOURS_OVER_CAP",),
    ),
    Mutation(
        "M42",
        "A weekday that does not match its date",
        _weekday_mismatch,
        expect_codes=("WEEKDAY_DATE_MISMATCH",),
    ),
    Mutation(
        "M67",
        "A notes page with no table",
        _notes_page,
        expect_codes=("PDF_TABLE_NOT_FOUND",),
        forbid_codes=("PDF_NO_TEXT_LAYER",),
    ),
    Mutation(
        "M66",
        "A page whose title names no known site",
        _unnamed_facility,
        expect_codes=("PDF_FACILITY_UNKNOWN",),
    ),
    Mutation(
        "M44",
        "The table spills onto a second page",
        _split_pages,
        forbid_codes=("PDF_TABLE_NOT_FOUND", "UNMATCHED_SCHEDULE"),
    ),
    Mutation(
        "M45", "A scanned rota with no text layer", _scanned, expect_codes=("PDF_NO_TEXT_LAYER",)
    ),
    Mutation(
        "M72", "A rota with no ruled lines at all", _no_grid, forbid_codes=("PDF_TABLE_NOT_FOUND",)
    ),
    # --- Domain -----------------------------------------------------------
    Mutation(
        "M73", "A census the roster cannot serve", _big_census, expect_codes=("HPRD_BELOW_MINIMUM",)
    ),
    Mutation(
        "M50",
        "An aide certification expiring mid-month",
        _aide_expiry_mid_month,
        expect_codes=("CNA_EXPIRY_NOT_MONTH_END",),
    ),
    # --- Everything at once ----------------------------------------------
    Mutation(
        "M48",
        "Kitchen sink: seven mutations together",
        _kitchen_sink,
        expect_codes=(
            "UNMATCHED_PAYROLL",
            "CODE_UNKNOWN_FACILITY",
            "VERIFICATION_STALE",
            "ROW_DROPPED_NONDATA",
            "FILE_TYPE_UNKNOWN",
            "RN_8H_COVERAGE_GAP",
            "FILE_DUPLICATE",
        ),
    ),
]


def prepare(mutation: Mutation, workspace: Path) -> Path:
    """Copy the clean set and break it in exactly one way."""
    target = workspace / mutation.id
    shutil.copytree(CLEAN, target)
    mutation.apply(target)
    return target
