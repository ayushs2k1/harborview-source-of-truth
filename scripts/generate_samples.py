"""Deterministic sample data generator.

Produces three healthcare sample sets:

* ``clean/``  - internally consistent. Every domain rule passes at the pinned as-of
  date, which makes it the baseline the chaos deck mutates and the control for "did we
  just break something".
* ``messy/``  - the clean set with specific problems planted, each annotated with the
  rule code it should raise. This is what ``make demo`` ingests.
* ``scan/``   - the schedule rasterized to an image-only PDF, with no text layer.

Design notes worth knowing before changing anything here:

**Coverage first, payroll second.** The schedule is authored to satisfy the domain rules
(an RN on duty eight consecutive hours at every facility every day, an aide on every
facility-day), and payroll is then *derived* from it. Writing payroll by hand and hoping
it reconciles is how fixtures drift; deriving it means the clean set reconciles by
construction, and a deliberate variance in the messy set is visible as an explicit
override rather than an arithmetic slip.

**Census is derived too.** Hours-per-resident-day minimums are a ratio, so a census
invented independently of the roster would put the clean set in violation. It is
computed from the schedule instead, which keeps the clean set green when staffing
changes. The messy set ships a realistic, deliberately under-staffed census so the
HPRD rule has something to find.

**No randomness.** ``--seed`` is accepted and threaded through for the larger generated
sets that come later, but ten people are hand-authored: intentional beats random when
every row has to carry a specific trap.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Imported after the sys.path line above: the two generators live side by side in
# scripts/ and are run directly, not installed as a package.
from make_schedule_pdf import (
    SchedulePage,
    ScheduleRow,
    rasterize_pdf,
    write_schedule_pdf,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The sample week. Monday to Sunday, matching the brief's pay period.
WEEK_START = date(2026, 9, 14)

#: Tests and fixtures pin this date so results never drift with the calendar.
PINNED_AS_OF = date(2026, 9, 21)

#: Shift lengths as printed in the page footnote. The adapter must parse this from the
#: page rather than assume it, so the generator and the engine share no constant.
FOOTNOTE_HOURS = {"7a-3p": 8.0, "3p-11p": 8.0, "11p-7a": 8.0, "7a-7p": 12.0}
FOOTNOTE_TEXT = "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."

#: Cell values that are not worked time.
OFF = "OFF"
PTO = "PTO"

#: PBJ meal deduction, mirrored from the pack so the derived census matches what the
#: engine will compute. Kept here only to size the census; the engine reads the pack.
MEAL_DEDUCTION_HOURS = 0.5
MEAL_MIN_SHIFT_HOURS = 6.0
HPRD_MINIMUMS = {"total": 3.5, "licensed": 1.1, "cna": 2.2}
LICENSED_ROLES = {"RN", "LPN"}
AIDE_ROLES = {"CNA"}


@dataclass(frozen=True)
class Facility:
    code: str
    name: str
    area_code: str


FACILITIES = (
    Facility("BYS", "Harborview Bayside", "718"),
    Facility("RVD", "Harborview Riverdale", "347"),
)

JOB_TITLES = {
    "RN": "Registered Nurse",
    "LPN": "Licensed Practical Nurse",
    "CNA": "Certified Nursing Assistant",
}


@dataclass(frozen=True)
class Person:
    """One employee, as the four systems each see them."""

    employee_id: str
    first_name: str
    last_name: str
    role: str
    home_facility: str
    phone: str
    license_number: str
    license_expiration: date
    hire_date: date
    last_verified: date
    #: How the schedule PDF writes them: often a nickname, sometimes without accents.
    schedule_name: str

    @property
    def payroll_name(self) -> str:
        """Payroll and the credential service both write ``LAST, FIRST`` in caps."""
        return f"{self.last_name.upper()}, {self.first_name.upper()}"

    @property
    def job_title(self) -> str:
        return JOB_TITLES[self.role]


def build_people() -> tuple[Person, ...]:
    """The roster.

    Two rows come from the brief verbatim. The rest are invented to carry the name
    shapes a real roster contains: an accent, a hyphenated surname, an apostrophe, a
    generational suffix, and a given name that is habitually shortened.
    """
    return (
        # --- Bayside -------------------------------------------------------
        Person(
            "E201",
            "Sofia",
            "Reyes",
            "RN",
            "BYS",
            "718-555-0201",
            "RN-551203",
            date(2027, 5, 31),
            date(2020, 3, 2),
            date(2026, 9, 1),
            schedule_name="Sofia Reyes",
        ),
        Person(
            "E203",
            "Katherine",
            "Doyle",
            "RN",
            "BYS",
            "718-555-0203",
            "RN-551884",
            date(2027, 8, 31),
            date(2019, 6, 17),
            date(2026, 9, 1),
            schedule_name="Kate Doyle",  # nickname, must still link
        ),
        Person(
            "E204",
            "José",
            "Peña",
            "LPN",
            "BYS",
            "718-555-0204",
            "LPN-330912",
            date(2028, 2, 29),
            date(2021, 1, 11),
            date(2026, 9, 1),
            schedule_name="José Peña",
        ),
        Person(
            "E205",
            "Ana",
            "García-López",
            "CNA",
            "BYS",
            "718-555-0205",
            "CNA-771920",
            date(2027, 4, 30),
            date(2022, 4, 4),
            date(2026, 9, 1),
            schedule_name="Ana García-López",
        ),
        Person(
            "E206",
            "Kevin",
            "O'Brien",
            "CNA",
            "BYS",
            "718-555-0206",
            "CNA-772145",
            date(2027, 10, 31),
            date(2023, 2, 20),
            date(2026, 9, 1),
            schedule_name="Kevin O'Brien",
        ),
        # --- Riverdale -----------------------------------------------------
        Person(
            "E202",
            "Marcus",
            "Bell",
            "CNA",
            "RVD",
            "347-555-0202",
            "CNA-771045",
            date(2026, 12, 31),
            date(2022, 9, 12),
            date(2026, 9, 1),
            schedule_name="Marc Bell",  # the brief's nickname
        ),
        Person(
            "E207",
            "Robert",
            "Hayes Jr.",
            "RN",
            "RVD",
            "347-555-0207",
            "RN-552401",
            date(2028, 1, 31),
            date(2018, 11, 5),
            date(2026, 9, 1),
            schedule_name="Robert Hayes Jr.",
        ),
        Person(
            "E208",
            "Priya",
            "Nair",
            "RN",
            "RVD",
            "347-555-0208",
            "RN-553077",
            date(2027, 11, 30),
            date(2021, 8, 30),
            date(2026, 9, 1),
            schedule_name="Priya Nair",  # the float: appears on both facility pages
        ),
        Person(
            "E209",
            "Daniel",
            "Okafor",
            "LPN",
            "RVD",
            "347-555-0209",
            "LPN-331455",
            date(2027, 9, 30),
            date(2020, 7, 13),
            date(2026, 9, 1),
            schedule_name="Daniel Okafor",
        ),
        Person(
            # Not "Grace": the no-hard-coding guard watches every fixture name, and
            # "grace period" is a phrase credential-expiry code will legitimately use.
            "E210",
            "Astrid",
            "Lindqvist",
            "CNA",
            "RVD",
            "347-555-0210",
            "CNA-773310",
            date(2027, 6, 30),
            date(2024, 3, 18),
            date(2026, 9, 1),
            schedule_name="Astrid Lindqvist",
        ),
    )


#: Who works where, in which facility's column on the printed page.
#:
#: Authored so that every facility-day has an RN on duty for at least eight consecutive
#: hours and at least one aide. Priya Nair appears on both pages: a legitimate float,
#: and the reason the four-way match has to reconcile per facility rather than per week.
Week = tuple[str, str, str, str, str, str, str]

CLEAN_SCHEDULE: dict[tuple[str, str], Week] = {
    # Bayside
    ("BYS", "E201"): ("7a-3p", "7a-3p", OFF, "7a-7p", OFF, "7a-3p", OFF),
    ("BYS", "E203"): (OFF, OFF, "7a-3p", OFF, "7a-3p", "7a-3p", "7a-3p"),
    ("BYS", "E204"): ("3p-11p", "3p-11p", "3p-11p", "3p-11p", "3p-11p", OFF, OFF),
    ("BYS", "E205"): ("7a-3p", "7a-3p", "7a-3p", "7a-3p", "7a-3p", OFF, OFF),
    ("BYS", "E206"): (OFF, OFF, "3p-11p", "3p-11p", "3p-11p", "7a-3p", "7a-3p"),
    ("BYS", "E208"): (OFF, OFF, OFF, "7a-3p", OFF, OFF, OFF),  # float from Riverdale
    # Riverdale
    ("RVD", "E202"): ("3p-11p", OFF, "3p-11p", "3p-11p", "3p-11p", "3p-11p", OFF),
    ("RVD", "E207"): (OFF, OFF, OFF, "7a-3p", "7a-3p", "7a-3p", "7a-3p"),
    ("RVD", "E208"): ("7a-3p", "7a-3p", "7a-3p", OFF, OFF, OFF, OFF),
    ("RVD", "E209"): ("7a-3p", "7a-3p", "7a-3p", "7a-3p", "7a-3p", OFF, OFF),
    ("RVD", "E210"): ("7a-3p", "7a-3p", "7a-3p", OFF, OFF, "7a-3p", "7a-3p"),
}


# ---------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------


def day_dates() -> list[date]:
    """The seven dates of the sample week."""
    return [WEEK_START + timedelta(days=offset) for offset in range(7)]


def day_headers() -> tuple[str, ...]:
    """Column headers as printed: weekday and M/D, with no year.

    The year is deliberately absent, exactly as in the brief. It forces the adapter to
    infer the year from the payroll periods rather than read it off the page.
    """
    return tuple(d.strftime("%a %m/%d") for d in day_dates())


def _clock_hours(token: str) -> float:
    """Duration of a ``7a-3p`` style token from the clock, overnight-aware.

    The footnote is authoritative where it speaks, but it does not define every shift a
    schedule can contain. Payroll has to pay for the hours actually worked, so the
    generator falls back to clock arithmetic exactly as the adapter will.
    """
    match = re.fullmatch(r"(\d{1,2})([ap])-(\d{1,2})([ap])", token.strip().lower())
    if not match:
        return 0.0
    start_hour, start_half, end_hour, end_half = match.groups()
    start = (int(start_hour) % 12) + (12 if start_half == "p" else 0)
    end = (int(end_hour) % 12) + (12 if end_half == "p" else 0)
    return float((end - start) % 24 or 24)


def cell_hours(cell: str) -> float:
    """Worked hours for one printed cell.

    Footnote first, clock second: the same precedence the adapter applies.
    """
    if cell in FOOTNOTE_HOURS:
        return FOOTNOTE_HOURS[cell]
    return _clock_hours(cell)


def scheduled_hours(
    schedule: dict[tuple[str, str], Week], facility: str, employee_id: str
) -> tuple[float, float]:
    """``(worked, pto)`` hours for one person at one facility across the week."""
    week = schedule.get((facility, employee_id))
    if week is None:
        return (0.0, 0.0)
    worked = sum(cell_hours(cell) for cell in week if cell not in {OFF, PTO})
    # A PTO day is paid at the shift length it replaced; these are all 8-hour days.
    pto = sum(8.0 for cell in week if cell == PTO)
    return (round(worked, 2), round(pto, 2))


@dataclass(frozen=True)
class PayrollRow:
    payroll_id: str
    employee_name: str
    job_code: str
    facility_code: str
    period_start: date
    period_end: date
    hours_paid: float
    #: Not written to the file; used by the generator to keep rows in a stable order.
    employee_id: str = ""
    #: When true, the writer emits the name unquoted so the comma splits the row.
    unquoted_name: bool = False


def derive_payroll(
    people: Sequence[Person], schedule: dict[tuple[str, str], Week]
) -> list[PayrollRow]:
    """One payroll row per person per facility they actually worked at.

    Paid hours are worked plus PTO, so the clean set reconciles by construction. A float
    gets one row per facility, which is what makes the per-facility match meaningful.
    """
    by_id = {person.employee_id: person for person in people}
    rows: list[PayrollRow] = []
    counter = 3001
    for facility, employee_id in sorted(schedule):
        person = by_id.get(employee_id)
        if person is None:
            continue
        worked, pto = scheduled_hours(schedule, facility, employee_id)
        if worked + pto <= 0:
            continue
        rows.append(
            PayrollRow(
                payroll_id=f"P-{counter}",
                employee_name=person.payroll_name,
                job_code=person.role,
                facility_code=facility,
                period_start=WEEK_START,
                period_end=WEEK_START + timedelta(days=6),
                hours_paid=round(worked + pto, 2),
                employee_id=employee_id,
            )
        )
        counter += 1
    return rows


def derive_census(schedule: dict[tuple[str, str], Week], people: Sequence[Person]) -> list[dict]:
    """A census the clean schedule can actually serve.

    Hours per resident per day is a ratio, so an invented census would put a compliant
    roster in violation. Working backwards from the schedule keeps the clean set green
    no matter how staffing is edited, and documents the relationship explicitly.
    """
    by_id = {person.employee_id: person for person in people}
    rows: list[dict] = []
    for facility in FACILITIES:
        daily_capacity: list[float] = []
        for index in range(len(day_dates())):
            totals = {"total": 0.0, "licensed": 0.0, "cna": 0.0}
            for (sched_facility, employee_id), week in sorted(schedule.items()):
                if sched_facility != facility.code:
                    continue
                person = by_id.get(employee_id)
                cell = week[index]
                if person is None or cell in {OFF, PTO}:
                    continue
                hours = cell_hours(cell)
                if hours >= MEAL_MIN_SHIFT_HOURS:
                    hours -= MEAL_DEDUCTION_HOURS
                totals["total"] += hours
                if person.role in LICENSED_ROLES:
                    totals["licensed"] += hours
                if person.role in AIDE_ROLES:
                    totals["cna"] += hours
            daily_capacity.append(
                min(totals[bucket] / minimum for bucket, minimum in HPRD_MINIMUMS.items())
            )
        # One number for the whole week, taken from the thinnest day. A census that rose
        # and fell with the rota would be an obvious artefact; residents do not go home
        # at the weekend. The thinnest day is also the one that has to stay compliant.
        residents = max(1, math.floor(min(daily_capacity)))
        rows.extend(
            {"facility": facility.code, "date": work_date.isoformat(), "residents": residents}
            for work_date in day_dates()
        )
    return rows


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    """Write a CSV deterministically: UTF-8, LF endings, minimal quoting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def write_hr_csv(path: Path, people: Sequence[Person]) -> None:
    """The HR roster: one row per employee, with the facility spelled out in full."""
    names = {facility.code: facility.name for facility in FACILITIES}
    _write_csv(
        path,
        [
            "employee_id",
            "first_name",
            "last_name",
            "job_title",
            "facility",
            "phone",
            "license_number",
            "license_expiration",
            "hire_date",
        ],
        [
            [
                person.employee_id,
                person.first_name,
                person.last_name,
                person.job_title,
                names[person.home_facility],
                person.phone,
                person.license_number,
                person.license_expiration.isoformat(),
                person.hire_date.isoformat(),
            ]
            for person in sorted(people, key=lambda p: p.employee_id)
        ],
    )


def write_payroll_csv(path: Path, rows: Sequence[PayrollRow]) -> None:
    """Payroll: no employee id, names as ``LAST, FIRST``, facility and job as codes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "payroll_id",
        "employee_name",
        "job_code",
        "facility_code",
        "period_start",
        "period_end",
        "hours_paid",
    ]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(",".join(header) + "\n")
        for row in rows:
            hours = f"{row.hours_paid:g}"
            if row.unquoted_name:
                # A real export that forgot to quote a field containing the delimiter.
                # The row now has one field too many and has to be repaired on read.
                name = row.employee_name
            else:
                name = f'"{row.employee_name}"'
            handle.write(
                ",".join(
                    [
                        row.payroll_id,
                        name,
                        row.job_code,
                        row.facility_code,
                        row.period_start.isoformat(),
                        row.period_end.isoformat(),
                        hours,
                    ]
                )
                + "\n"
            )


def write_licenses_csv(path: Path, people: Sequence[Person]) -> None:
    """The verification service's export: credential number is the anchor."""
    _write_csv(
        path,
        ["license_number", "name_on_license", "license_type", "expiration_date", "last_verified"],
        [
            [
                person.license_number,
                person.payroll_name,
                person.role,
                person.license_expiration.isoformat(),
                person.last_verified.isoformat(),
            ]
            for person in sorted(people, key=lambda p: p.license_number)
        ],
    )


def write_census_csv(path: Path, rows: Sequence[dict]) -> None:
    _write_csv(
        path,
        ["facility", "date", "residents"],
        [[row["facility"], row["date"], row["residents"]] for row in rows],
    )


def write_vendor_documents_csv(path: Path, *, expiring: bool = False) -> None:
    """Vendor paperwork, modelled as credentials held by an organisation."""
    rows = [
        [
            "Coastal Linen Services",
            "Certificate of Insurance",
            "COI-88421",
            "2027-03-31",
            "2026-09-01",
        ],
        ["Metro Medical Waste", "Hauler Permit", "MWP-20314", "2027-06-30", "2026-09-01"],
        ["Harbor Pharmacy Partners", "Pharmacy License", "PHR-44190", "2027-01-31", "2026-09-01"],
    ]
    if expiring:
        # Planted: a vendor permit lapsing inside the 90-day window, verified long ago.
        rows.append(
            [
                "Northside Elevator Co",
                "Inspection Certificate",
                "ELV-10277",
                "2026-10-30",
                "2026-02-11",
            ]
        )
    _write_csv(path, ["vendor", "doc_type", "doc_number", "expires_on", "verified_on"], rows)


def build_schedule_pages(
    people: Sequence[Person],
    schedule: dict[tuple[str, str], Week],
    *,
    extra_rows: dict[str, list[ScheduleRow]] | None = None,
    footnote: str | None = FOOTNOTE_TEXT,
) -> list[SchedulePage]:
    """One page per facility, staff in roster order, the footnote at the bottom."""
    by_id = {person.employee_id: person for person in people}
    pages: list[SchedulePage] = []
    for facility in FACILITIES:
        rows: list[ScheduleRow] = []
        for (sched_facility, employee_id), week in sorted(schedule.items()):
            if sched_facility != facility.code:
                continue
            person = by_id.get(employee_id)
            if person is None:
                continue
            rows.append(ScheduleRow(person.schedule_name, person.role, week))
        rows.extend((extra_rows or {}).get(facility.code, []))
        pages.append(
            SchedulePage(
                facility_label=facility.name,
                week_label=f"Week of {WEEK_START.strftime('%a %m/%d')}",
                day_headers=day_headers(),
                rows=tuple(rows),
                footnote=footnote,
            )
        )
    return pages


# ---------------------------------------------------------------------------
# Sample sets
# ---------------------------------------------------------------------------


def build_clean(out_dir: Path) -> list[Path]:
    """The consistent baseline. Nothing here should raise above INFO."""
    people = build_people()
    payroll = derive_payroll(people, CLEAN_SCHEDULE)
    written: list[Path] = []

    write_hr_csv(out_dir / "roster_export.csv", people)
    write_payroll_csv(out_dir / "pay_register_2026-09-20.csv", payroll)
    write_licenses_csv(out_dir / "license_verification.csv", people)
    write_census_csv(out_dir / "census.csv", derive_census(CLEAN_SCHEDULE, people))
    write_vendor_documents_csv(out_dir / "vendor_documents.csv")
    write_schedule_pdf(
        out_dir / "weekly_schedule.pdf", build_schedule_pages(people, CLEAN_SCHEDULE)
    )
    written.extend(sorted(out_dir.iterdir()))
    return written


def build_messy(out_dir: Path) -> list[Path]:
    """The clean set with specific, individually justified problems planted.

    Every mutation below names the rule code it is there to raise, so a change in the
    engine that stops detecting one of them shows up as a missing flag rather than as a
    fixture nobody can explain.
    """
    people = list(build_people())
    schedule = dict(CLEAN_SCHEDULE)
    by_id = {person.employee_id: person for person in people}

    # -- Credentials -------------------------------------------------------

    def amend(employee_id: str, **changes) -> None:
        index = next(i for i, p in enumerate(people) if p.employee_id == employee_id)
        people[index] = replace(people[index], **changes)

    # WORKED_AFTER_EXPIRY + CREDENTIAL_EXPIRED: certification lapsed mid-week, with
    # shifts on both sides of the expiry date.
    amend("E210", license_expiration=date(2026, 9, 17))
    # CREDENTIAL_EXPIRING (WARNING band): 70 days out from the pinned as-of date.
    amend("E209", license_expiration=date(2026, 11, 30))
    # VERIFICATION_STALE: last checked well beyond verification_max_age_days.
    amend("E207", last_verified=date(2026, 5, 15))
    # Schedule spells an accented name without its accents; must still link.
    amend("E204", schedule_name="Jose Pena")

    # -- Schedule ----------------------------------------------------------

    # RN_8H_COVERAGE_GAP: Riverdale loses its only Sunday RN.
    schedule[("RVD", "E207")] = ("OFF", "OFF", "OFF", "7a-3p", "7a-3p", "7a-3p", OFF)
    # HOURS_VARIANCE explained by PTO: paid for a full week, one day taken as leave.
    schedule[("BYS", "E205")] = ("7a-3p", "7a-3p", "7a-3p", PTO, "7a-3p", OFF, OFF)
    # SHIFT_NOT_IN_FOOTNOTE (+ SHIFT_SPANS_PERIOD): a 12-hour night the footnote
    # does not define, running past the end of the period.
    schedule[("BYS", "E206")] = (OFF, OFF, "3p-11p", "3p-11p", "3p-11p", "7a-3p", "7p-7a")
    # An overnight the footnote *does* define, which PBJ must split at midnight.
    schedule[("RVD", "E209")] = ("7a-3p", "7a-3p", "7a-3p", "7a-3p", "7a-3p", "11p-7a", OFF)

    # UNMATCHED_SCHEDULE: agency nurse on the page and in no other system.
    agency = {
        "BYS": [ScheduleRow("L. Okonkwo", "RN", (OFF, "3p-11p", OFF, OFF, "3p-11p", OFF, OFF))]
    }

    payroll = derive_payroll(people, schedule)
    next_id = 3001 + len(payroll)

    def override(employee_id: str, facility: str, hours: float) -> None:
        for index, row in enumerate(payroll):
            if row.employee_id == employee_id and row.facility_code == facility:
                payroll[index] = replace(row, hours_paid=hours)
                return

    # HOURS_VARIANCE, unexplained: paid four hours fewer than scheduled.
    override("E209", "RVD", 44.0)
    # ROW_DELIMITER_REPAIRED: the name field is written without its quotes.
    for index, row in enumerate(payroll):
        if row.employee_id == "E210":
            payroll[index] = replace(row, unquoted_name=True)

    marcus = by_id["E202"]
    payroll.extend(
        [
            # UNMATCHED_PAYROLL: paid, but in no other system. A ghost employee, or
            # agency staff nobody recorded - either way, money leaving the building.
            PayrollRow(
                f"P-{next_id}",
                "TORRES, MIGUEL",
                "CNA",
                "RVD",
                WEEK_START,
                WEEK_START + timedelta(days=6),
                32.0,
                employee_id="",
            ),
            # DUPLICATE_PAY_PERIOD: the same person, period, facility, and role twice.
            PayrollRow(
                f"P-{next_id + 1}",
                marcus.payroll_name,
                "CNA",
                "RVD",
                WEEK_START,
                WEEK_START + timedelta(days=6),
                40.0,
                employee_id="E202",
            ),
            # CODE_UNKNOWN_FACILITY: a site code that is in no crosswalk.
            PayrollRow(
                f"P-{next_id + 2}",
                by_id["E203"].payroll_name,
                "RN",
                "HVB",
                WEEK_START,
                WEEK_START + timedelta(days=6),
                4.0,
                employee_id="E203",
            ),
        ]
    )

    # HR_LICENSE_EXPIRY_STALE: HR's copy of the expiry disagrees with the service.
    license_people = [
        replace(person, license_expiration=date(2027, 7, 31))
        if person.employee_id == "E201"
        else person
        for person in people
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_hr_csv(out_dir / "HR_FINAL_v2.csv", people)
    write_payroll_csv(out_dir / "payroll_wk38.csv", payroll)
    write_licenses_csv(out_dir / "licenses.csv", license_people)
    # A realistic census the roster cannot actually serve, so HPRD has something to say.
    write_census_csv(
        out_dir / "census.csv",
        [
            {"facility": facility.code, "date": work_date.isoformat(), "residents": residents}
            for facility, residents in ((FACILITIES[0], 28), (FACILITIES[1], 24))
            for work_date in day_dates()
        ],
    )
    write_vendor_documents_csv(out_dir / "vendor_documents.csv", expiring=True)
    write_schedule_pdf(
        out_dir / "schedule.pdf",
        build_schedule_pages(people, schedule, extra_rows=agency),
    )
    return sorted(out_dir.iterdir())


def build_scan(out_dir: Path, source_pdf: Path) -> list[Path]:
    """The schedule as a photocopy: page images, no text layer."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rasterize_pdf(source_pdf, out_dir / "scanned_schedule.pdf")
    return sorted(out_dir.iterdir())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="reserved for generated sets")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "data" / "samples" / "healthcare"),
        help="directory to write the sample sets into",
    )
    args = parser.parse_args()

    base = Path(args.out)
    clean = build_clean(base / "clean")
    messy = build_messy(base / "messy")
    scan = build_scan(base / "scan", base / "clean" / "weekly_schedule.pdf")

    for label, paths in (("clean", clean), ("messy", messy), ("scan", scan)):
        print(f"{label}/")
        for path in paths:
            print(f"  {path.name:<34} {path.stat().st_size:>8,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
