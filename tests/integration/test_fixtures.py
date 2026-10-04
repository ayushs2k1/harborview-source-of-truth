"""The generated sample sets.

The engine does not exist yet at this phase, so these assert properties of the fixtures
themselves. They matter because every later phase measures itself against them: if the
clean set is quietly not compliant, "the clean set raises nothing above INFO" stops
being a meaningful gate and starts being a thing we edit until it passes.
"""

from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pdfplumber
import pytest
import yaml

SAMPLES = Path(__file__).resolve().parent.parent.parent / "data" / "samples" / "healthcare"
PACK = Path(__file__).resolve().parent.parent.parent / "packs" / "healthcare_ny" / "pack.yaml"
SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"

PINNED_AS_OF = date(2026, 9, 21)
PERIOD_START = date(2026, 9, 14)
PERIOD_END = date(2026, 9, 20)


@pytest.fixture(scope="module")
def pack() -> dict:
    return yaml.safe_load(PACK.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_shift(token: str) -> tuple[float, float] | None:
    """``7a-3p`` to ``(7, 15)``; overnight tokens end past 24."""
    import re

    match = re.fullmatch(r"(\d{1,2})([ap])-(\d{1,2})([ap])", token.strip().lower())
    if not match:
        return None
    start_hour, start_half, end_hour, end_half = match.groups()
    start = (int(start_hour) % 12) + (12 if start_half == "p" else 0)
    end = (int(end_hour) % 12) + (12 if end_half == "p" else 0)
    if end <= start:
        end += 24
    return (float(start), float(end))


def longest_covered_run(intervals: list[tuple[float, float]]) -> float:
    """Longest unbroken stretch covered by the union of ``intervals``."""
    if not intervals:
        return 0.0
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return max(end - start for start, end in merged)


# ---------------------------------------------------------------------------
# The sets exist and are reproducible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("folder", "names"),
    [
        (
            "clean",
            {
                "roster_export.csv",
                "pay_register_2026-09-20.csv",
                "license_verification.csv",
                "census.csv",
                "vendor_documents.csv",
                "weekly_schedule.pdf",
            },
        ),
        (
            "messy",
            {
                "HR_FINAL_v2.csv",
                "payroll_wk38.csv",
                "licenses.csv",
                "census.csv",
                "vendor_documents.csv",
                "schedule.pdf",
            },
        ),
        ("scan", {"scanned_schedule.pdf"}),
    ],
)
def test_sample_sets_exist(folder: str, names: set[str]):
    assert {p.name for p in (SAMPLES / folder).iterdir()} == names


def test_generator_is_byte_reproducible(tmp_path: Path):
    """Same seed, same bytes. A fixture that drifts makes every diff unreadable."""

    def generate(target: Path) -> dict[str, str]:
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "generate_samples.py"),
                "--seed",
                "42",
                "--out",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
        return {
            str(path.relative_to(target)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(target.rglob("*"))
            if path.is_file()
        }

    first = generate(tmp_path / "a")
    second = generate(tmp_path / "b")
    assert first == second
    assert len(first) >= 13


def test_committed_fixtures_match_the_generator(tmp_path: Path):
    """The files in the repo are what the generator produces right now."""
    subprocess.run(
        [sys.executable, str(SCRIPTS / "generate_samples.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    for produced in sorted(tmp_path.rglob("*")):
        if not produced.is_file():
            continue
        committed = SAMPLES / produced.relative_to(tmp_path)
        assert committed.exists(), f"{committed} is missing; run make samples"
        assert committed.read_bytes() == produced.read_bytes(), (
            f"{committed} is stale; run make samples"
        )


# ---------------------------------------------------------------------------
# The clean set is actually clean
# ---------------------------------------------------------------------------


def test_clean_payroll_reconciles_with_the_clean_schedule():
    """Paid equals scheduled, per person per facility. The whole demo rests on this."""
    sys.path.insert(0, str(SCRIPTS))
    import generate_samples as gen

    people = {p.employee_id: p for p in gen.build_people()}
    expected = {
        (person.payroll_name, facility): sum(gen.scheduled_hours(gen.CLEAN_SCHEDULE, facility, eid))
        for (facility, eid) in gen.CLEAN_SCHEDULE
        if (person := people.get(eid)) is not None
    }
    for row in read_csv(SAMPLES / "clean" / "pay_register_2026-09-20.csv"):
        key = (row["employee_name"], row["facility_code"])
        assert float(row["hours_paid"]) == pytest.approx(expected[key]), key


def test_clean_schedule_has_rn_coverage_every_facility_day(pack: dict):
    """The federal rule the pack encodes: an RN on duty eight consecutive hours."""
    sys.path.insert(0, str(SCRIPTS))
    import generate_samples as gen

    required = float(pack["rn_min_consecutive_hours"])
    people = {p.employee_id: p for p in gen.build_people()}
    for facility in ("BYS", "RVD"):
        for day_index in range(7):
            intervals = []
            for (sched_facility, employee_id), week in gen.CLEAN_SCHEDULE.items():
                person = people[employee_id]
                if sched_facility != facility or person.role != "RN":
                    continue
                parsed = parse_shift(week[day_index])
                if parsed:
                    intervals.append(parsed)
            covered = longest_covered_run(intervals)
            assert covered >= required, (
                f"{facility} day {day_index} has only {covered}h of RN cover"
            )


def test_clean_schedule_has_an_aide_every_facility_day():
    """Without an aide on every day the CNA hours-per-resident minimum cannot be met."""
    sys.path.insert(0, str(SCRIPTS))
    import generate_samples as gen

    people = {p.employee_id: p for p in gen.build_people()}
    for facility in ("BYS", "RVD"):
        for day_index in range(7):
            aides = [
                week[day_index]
                for (sched_facility, employee_id), week in gen.CLEAN_SCHEDULE.items()
                if sched_facility == facility
                and people[employee_id].role == "CNA"
                and parse_shift(week[day_index])
            ]
            assert aides, f"{facility} day {day_index} has no aide on duty"


def test_clean_census_satisfies_every_hprd_minimum(pack: dict):
    """Hours per resident per day is a ratio, so the census is part of being compliant."""
    sys.path.insert(0, str(SCRIPTS))
    import generate_samples as gen

    minimums = pack["hprd_minimums"]
    meal = pack["pbj"]["meal_deduction"]
    people = {p.employee_id: p for p in gen.build_people()}
    census = {
        (row["facility"], row["date"]): int(row["residents"])
        for row in read_csv(SAMPLES / "clean" / "census.csv")
    }

    for facility in ("BYS", "RVD"):
        for day_index, work_date in enumerate(gen.day_dates()):
            buckets = {"total": 0.0, "licensed": 0.0, "cna": 0.0}
            for (sched_facility, employee_id), week in gen.CLEAN_SCHEDULE.items():
                if sched_facility != facility:
                    continue
                person = people[employee_id]
                hours = gen.cell_hours(week[day_index])
                if hours <= 0:
                    continue
                if hours >= meal["min_shift_hours"]:
                    hours -= meal["minutes"] / 60.0
                buckets["total"] += hours
                if person.role in {"RN", "LPN"}:
                    buckets["licensed"] += hours
                if person.role == "CNA":
                    buckets["cna"] += hours

            residents = census[(facility, work_date.isoformat())]
            for bucket, minimum in minimums.items():
                hprd = buckets[bucket] / residents
                assert hprd >= minimum, (
                    f"{facility} {work_date} {bucket}: {hprd:.2f} below {minimum}"
                )


def test_clean_credentials_are_outside_every_expiry_window(pack: dict):
    """Nothing in the clean set may be expiring, or the baseline is not green."""
    widest = max(pack["expiry_windows_days"])
    for row in read_csv(SAMPLES / "clean" / "license_verification.csv"):
        expires = date.fromisoformat(row["expiration_date"])
        days_left = (expires - PINNED_AS_OF).days
        assert days_left > widest, f"{row['license_number']} expires in {days_left} days"


def test_clean_verifications_are_fresh(pack: dict):
    limit = pack["verification_max_age_days"]
    for row in read_csv(SAMPLES / "clean" / "license_verification.csv"):
        age = (PINNED_AS_OF - date.fromisoformat(row["last_verified"])).days
        assert 0 <= age <= limit, f"{row['license_number']} verified {age} days ago"


def test_clean_aide_certifications_expire_on_a_month_end():
    """New York CNA renewals fall on month ends; anything else is a data-entry error."""
    for row in read_csv(SAMPLES / "clean" / "license_verification.csv"):
        if row["license_type"] != "CNA":
            continue
        expires = date.fromisoformat(row["expiration_date"])
        following = expires.replace(day=28) + timedelta(days=4)
        last_day = following - timedelta(days=following.day)
        assert expires == last_day, f"{row['license_number']} expires {expires}"


def test_clean_roster_predates_the_pay_period():
    for row in read_csv(SAMPLES / "clean" / "roster_export.csv"):
        assert date.fromisoformat(row["hire_date"]) < PERIOD_START


def test_hr_and_the_credential_service_agree_in_the_clean_set():
    roster = {r["license_number"]: r for r in read_csv(SAMPLES / "clean" / "roster_export.csv")}
    for row in read_csv(SAMPLES / "clean" / "license_verification.csv"):
        assert roster[row["license_number"]]["license_expiration"] == row["expiration_date"]


def test_the_float_has_one_payroll_row_per_facility():
    rows = read_csv(SAMPLES / "clean" / "pay_register_2026-09-20.csv")
    counts: dict[str, list[str]] = {}
    for row in rows:
        counts.setdefault(row["employee_name"], []).append(row["facility_code"])
    floats = {name: sites for name, sites in counts.items() if len(sites) > 1}
    assert len(floats) == 1, "the sample needs exactly one cross-facility float"
    (sites,) = floats.values()
    assert sorted(sites) == ["BYS", "RVD"]
    assert len(set(sites)) == len(sites), "one row per facility, not two at the same site"


def test_clean_roster_carries_the_awkward_name_shapes():
    """Accents, hyphens, apostrophes, and suffixes all have to survive the round trip."""
    roster = read_csv(SAMPLES / "clean" / "roster_export.csv")
    surnames = {row["last_name"] for row in roster}
    assert any("ñ" in name for name in surnames), "no accented surname"
    assert any("-" in name for name in surnames), "no hyphenated surname"
    assert any("'" in name for name in surnames), "no apostrophe surname"
    assert any(name.endswith("Jr.") for name in surnames), "no generational suffix"


# ---------------------------------------------------------------------------
# The schedule PDF
# ---------------------------------------------------------------------------


def test_clean_pdf_has_one_page_per_facility_with_a_parseable_table():
    with pdfplumber.open(SAMPLES / "clean" / "weekly_schedule.pdf") as pdf:
        assert len(pdf.pages) == 2
        for page in pdf.pages:
            tables = page.extract_tables()
            assert tables, "the ruled grid should give pdfplumber a table directly"
            header = tables[0][0]
            assert header[0] == "Staff" and header[1] == "Role"
            assert len(header) == 9, "two label columns plus seven days"
            assert "are 8 hours" in (page.extract_text() or ""), "footnote missing"


def test_pdf_day_headers_carry_no_year():
    """Exactly as in the brief. The year has to be inferred from the payroll periods."""
    with pdfplumber.open(SAMPLES / "clean" / "weekly_schedule.pdf") as pdf:
        header = pdf.pages[0].extract_tables()[0][0]
    for cell in header[2:]:
        assert "2026" not in cell
        assert cell[:3] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_pdf_pages_name_their_facility():
    with pdfplumber.open(SAMPLES / "clean" / "weekly_schedule.pdf") as pdf:
        labels = [(page.extract_text() or "").splitlines()[0] for page in pdf.pages]
    assert len(set(labels)) == 2, "each page should name a different facility"


def test_scanned_pdf_has_no_text_layer():
    """The photocopy case. It must reach the adapter as an image, not as text."""
    with pdfplumber.open(SAMPLES / "scan" / "scanned_schedule.pdf") as pdf:
        assert len(pdf.pages) == 2
        for page in pdf.pages:
            assert not (page.extract_text() or "").strip()
            assert page.images, "a scanned page should be an image"


# ---------------------------------------------------------------------------
# The messy set carries the problems it is supposed to carry
# ---------------------------------------------------------------------------


def test_messy_payroll_has_a_row_whose_name_is_not_quoted():
    """A real export that forgot to quote a field containing the delimiter.

    Counted through a CSV reader, not by splitting on commas: a correctly quoted
    ``"LAST, FIRST"`` also contains a comma, and the whole point is that one row does
    not have the quotes that make it safe.
    """
    with open(SAMPLES / "messy" / "payroll_wk38.csv", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    expected = len(rows[0])
    ragged = [row for row in rows[1:] if len(row) != expected]
    assert len(ragged) == 1, f"expected one unquoted name, found {len(ragged)}"
    assert len(ragged[0]) == expected + 1, "the stray comma should add exactly one field"


def test_messy_payroll_has_a_person_who_is_in_no_other_system():
    roster_names = {
        f"{r['last_name'].upper()}, {r['first_name'].upper()}"
        for r in read_csv(SAMPLES / "messy" / "HR_FINAL_v2.csv")
    }
    payroll_names = {
        r["employee_name"]
        for r in read_csv(SAMPLES / "messy" / "payroll_wk38.csv")
        if r["employee_name"]
    }
    assert payroll_names - roster_names, "no ghost payroll row planted"


def test_messy_payroll_has_a_duplicated_pay_period():
    seen: set[tuple[str, str, str, str]] = set()
    duplicates = []
    for row in read_csv(SAMPLES / "messy" / "payroll_wk38.csv"):
        key = (row["employee_name"], row["facility_code"], row["job_code"], row["period_start"])
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    assert duplicates, "no duplicate pay period planted"


def test_messy_payroll_has_a_facility_code_outside_the_crosswalk():
    known = {"BYS", "RVD"}
    codes = {r["facility_code"] for r in read_csv(SAMPLES / "messy" / "payroll_wk38.csv")}
    assert codes - known, "no unknown facility code planted"


def test_messy_credentials_include_an_expired_one_and_an_expiring_one(pack: dict):
    rows = read_csv(SAMPLES / "messy" / "licenses.csv")
    days = [(date.fromisoformat(r["expiration_date"]) - PINNED_AS_OF).days for r in rows]
    assert any(d < 0 for d in days), "no expired credential planted"
    assert any(0 <= d <= max(pack["expiry_windows_days"]) for d in days), "none expiring"


def test_messy_credentials_include_a_stale_verification(pack: dict):
    limit = pack["verification_max_age_days"]
    ages = [
        (PINNED_AS_OF - date.fromisoformat(r["last_verified"])).days
        for r in read_csv(SAMPLES / "messy" / "licenses.csv")
    ]
    assert any(age > limit for age in ages), "no stale verification planted"


def test_messy_hr_disagrees_with_the_credential_service_on_one_expiry():
    roster = {r["license_number"]: r for r in read_csv(SAMPLES / "messy" / "HR_FINAL_v2.csv")}
    mismatches = [
        row["license_number"]
        for row in read_csv(SAMPLES / "messy" / "licenses.csv")
        if roster[row["license_number"]]["license_expiration"] != row["expiration_date"]
    ]
    assert len(mismatches) == 1, f"expected exactly one stale HR expiry, got {mismatches}"


def test_messy_schedule_has_a_person_in_no_other_system():
    with pdfplumber.open(SAMPLES / "messy" / "schedule.pdf") as pdf:
        staff = {
            row[0] for page in pdf.pages for row in page.extract_tables()[0][1:] if row and row[0]
        }
    roster = read_csv(SAMPLES / "messy" / "HR_FINAL_v2.csv")
    surnames = {row["last_name"].split()[0].lower() for row in roster}
    unknown = [name for name in staff if not any(s in name.lower() for s in surnames)]
    assert unknown, "no agency nurse planted on the schedule"


def test_messy_schedule_has_leave_a_shift_outside_the_footnote_and_an_overnight():
    with pdfplumber.open(SAMPLES / "messy" / "schedule.pdf") as pdf:
        cells = {
            cell
            for page in pdf.pages
            for row in page.extract_tables()[0][1:]
            for cell in (row[2:] if row else [])
            if cell
        }
    footnote_shifts = {"7a-3p", "3p-11p", "11p-7a", "7a-7p"}
    assert "PTO" in cells, "no paid leave planted"
    assert "11p-7a" in cells, "no overnight planted"
    undefined = {c for c in cells if parse_shift(c) and c not in footnote_shifts}
    assert undefined, "no shift outside the footnote planted"


def test_messy_schedule_leaves_a_facility_day_without_an_rn():
    """The planted coverage gap the domain rule has to find."""
    sys.path.insert(0, str(SCRIPTS))
    import generate_samples as gen

    with pdfplumber.open(SAMPLES / "messy" / "schedule.pdf") as pdf:
        gaps = []
        for page in pdf.pages:
            table = page.extract_tables()[0]
            facility = (page.extract_text() or "").splitlines()[0]
            for day_index in range(7):
                intervals = []
                for row in table[1:]:
                    if not row or row[1] != "RN":
                        continue
                    parsed = parse_shift(row[2 + day_index] or "")
                    if parsed:
                        intervals.append(parsed)
                if longest_covered_run(intervals) < 8:
                    gaps.append((facility, day_index))
    assert gaps, "no RN coverage gap planted"
    assert gen.PINNED_AS_OF == PINNED_AS_OF, "the generator and the tests must pin the same date"


def test_messy_census_is_too_large_for_the_roster(pack: dict):
    """Planted so the hours-per-resident rule has something to report."""
    clean = {int(r["residents"]) for r in read_csv(SAMPLES / "clean" / "census.csv")}
    messy = {int(r["residents"]) for r in read_csv(SAMPLES / "messy" / "census.csv")}
    assert min(messy) > max(clean)


def test_messy_vendor_documents_include_one_expiring(pack: dict):
    rows = read_csv(SAMPLES / "messy" / "vendor_documents.csv")
    widest = max(pack["expiry_windows_days"])
    soon = [
        r for r in rows if 0 <= (date.fromisoformat(r["expires_on"]) - PINNED_AS_OF).days <= widest
    ]
    assert soon, "no expiring vendor document planted"


def test_the_generator_never_reads_the_clock():
    """Fixtures must not move with the calendar.

    A generator that reached for today's date would produce different files tomorrow,
    and every test that measures against them would start failing on a date nobody
    chose. Checked by reading the source, because the symptom is invisible for a day.
    """
    for script in ("generate_samples.py", "make_schedule_pdf.py"):
        source = (SCRIPTS / script).read_text(encoding="utf-8")
        for forbidden in ("date.today()", "datetime.now()", "datetime.utcnow()", "time.time()"):
            assert forbidden not in source, f"{script} reads the clock via {forbidden}"


def test_the_pinned_date_sits_just_after_the_pay_period():
    """Compliance is judged as of a date; this one is the day after the sample week."""
    assert PERIOD_START < PERIOD_END < PINNED_AS_OF
    assert (PINNED_AS_OF - PERIOD_END).days == 1
