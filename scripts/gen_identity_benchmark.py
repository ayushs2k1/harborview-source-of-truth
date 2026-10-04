"""A seeded identity benchmark with known ground truth.

Ten people cannot tell you whether a matcher works. This builds a larger synthetic
roster - sixty people over four weeks - where every generated record records which
person it is really about, so linkage precision and recall can be measured rather
than asserted.

The corruptions are the ones that actually occur: a shortened given name, dropped
accents, a transposition, an initial instead of a name, family-name-first ordering,
and shouting. The hard cases are planted deliberately - people who share a surname,
people who share a given name, and surnames one character apart - because a matcher
that only sees easy pairs will score well and still be wrong on the day.

Importable, so a test can measure against it without touching the filesystem.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

GIVEN_NAMES = [
    "Margaret",
    "Thomas",
    "Priscilla",
    "Desmond",
    "Imani",
    "Rohan",
    "Beatrice",
    "Hugo",
    "Yolanda",
    "Anselm",
    "Clarissa",
    "Ferdinand",
    "Noor",
    "Oleg",
    "Perpetua",
    "Quentin",
    "Rosalind",
    "Soren",
    "Tabitha",
    "Ulysses",
    "Verity",
    "Wilhelmina",
    "Xiomara",
    "Yusuf",
    "Zara",
    "Bartholomew",
    "Cordelia",
    "Dmitri",
    "Esperanza",
    "Fionnuala",
]
FAMILY_NAMES = [
    "Abernathy",
    "Castellanos",
    "Dunwoody",
    "Eastleigh",
    "Fairweather",
    "Gudmundsson",
    "Halloran",
    "Ibarra",
    "Jankowski",
    "Kowalczyk",
    "Lindgren",
    "Mbeki",
    "Nakamura",
    "Oyelaran",
    "Pettersson",
    "Quintanilla",
    "Radcliffe",
    "Stavrakis",
    "Thorvaldsen",
    "Ueda",
    "Vasquez",
    "Whitmore",
    "Xanthopoulos",
    "Yamashita",
    "Zielinski",
]
ROLES = ["RN", "LPN", "CNA"]
FACILITIES = ["SITE_A", "SITE_B"]

#: Short forms the nickname table knows, used so the matcher has to earn the link.
NICKNAMES = {
    "Margaret": "Peggy",
    "Thomas": "Tom",
    "Priscilla": "Cilla",
    "Beatrice": "Bea",
    "Quentin": "Quent",
    "Rosalind": "Ros",
    "Tabitha": "Tabby",
    "Cordelia": "Delia",
}


@dataclass(frozen=True)
class BenchPerson:
    person_id: str
    employee_id: str
    given: str
    family: str
    role: str
    facility: str
    credential: str = ""

    @property
    def full(self) -> str:
        return f"{self.given} {self.family}"


@dataclass(frozen=True)
class BenchMention:
    record_id: str
    source_role: str
    written_name: str
    role: str
    facility: str
    credential: str = ""
    #: The person this record is really about. Never shown to the matcher.
    truth: str = ""


@dataclass
class Benchmark:
    people: list[BenchPerson] = field(default_factory=list)
    mentions: list[BenchMention] = field(default_factory=list)

    @property
    def truth(self) -> dict[str, str]:
        return {mention.record_id: mention.truth for mention in self.mentions}


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _transpose(text: str, rng: random.Random) -> str:
    if len(text) < 4:
        return text
    index = rng.randrange(1, len(text) - 2)
    return text[:index] + text[index + 1] + text[index] + text[index + 2 :]


def corrupt(person: BenchPerson, rng: random.Random) -> str:
    """Write a person's name the way some other system would have."""
    style = rng.choice(
        ["plain", "last_first", "shouted", "nickname", "initial", "typo", "accentless", "middle"]
    )
    given, family = person.given, person.family
    if style == "nickname":
        given = NICKNAMES.get(given, given)
    if style == "typo":
        family = _transpose(family, rng)
    if style == "accentless":
        given, family = _strip_accents(given), _strip_accents(family)
    if style == "initial":
        given = f"{given[0]}."
    if style == "middle":
        return f"{given} {rng.choice('ABCDEFGHJKLM')}. {family}"
    if style == "last_first":
        return f"{family}, {given}"
    if style == "shouted":
        return f"{family.upper()}, {given.upper()}"
    return f"{given} {family}"


def build(seed: int = 42, people_count: int = 60, weeks: int = 4) -> Benchmark:
    """Build the benchmark. Deterministic for a given seed."""
    rng = random.Random(seed)
    bench = Benchmark()

    combinations: list[tuple[str, str]] = []
    # Planted hard cases first: shared surnames, shared given names, and near-misses.
    combinations += [("Margaret", "Halloran"), ("Marcus", "Halloran"), ("Margarita", "Halloran")]
    combinations += [("Thomas", "Lindgren"), ("Thomas", "Lindgrem"), ("Thomas", "Lindqren")]
    combinations += [("Imani", "Mbeki"), ("Imani", "Nakamura")]
    while len(combinations) < people_count:
        pair = (rng.choice(GIVEN_NAMES), rng.choice(FAMILY_NAMES))
        if pair not in combinations:
            combinations.append(pair)

    for index, (given, family) in enumerate(combinations[:people_count]):
        role = ROLES[index % len(ROLES)]
        person = BenchPerson(
            person_id=f"P-B{index:03d}",
            employee_id=f"B{index:03d}",
            given=given,
            family=family,
            role=role,
            facility=FACILITIES[index % len(FACILITIES)],
            # Two in three carry a credential number, as a real roster does.
            credential=f"{role}-{700000 + index}" if index % 3 else "",
        )
        bench.people.append(person)

    for week in range(weeks):
        for person in bench.people:
            bench.mentions.append(
                BenchMention(
                    record_id=f"PAY-{week}-{person.employee_id}",
                    source_role="payroll",
                    written_name=corrupt(person, rng),
                    role=person.role,
                    facility=person.facility,
                    truth=person.person_id,
                )
            )
            bench.mentions.append(
                BenchMention(
                    record_id=f"SCH-{week}-{person.employee_id}",
                    source_role="schedule",
                    written_name=corrupt(person, rng),
                    role=person.role,
                    # A tenth of shifts are at the other site, as floats are.
                    facility=(
                        person.facility
                        if rng.random() > 0.1
                        else next(site for site in FACILITIES if site != person.facility)
                    ),
                    truth=person.person_id,
                )
            )
        for person in bench.people:
            if week == 0 and person.credential:
                bench.mentions.append(
                    BenchMention(
                        record_id=f"CRED-{person.employee_id}",
                        source_role="credentials",
                        written_name=corrupt(person, rng),
                        role=person.role,
                        facility="",
                        credential=person.credential,
                        truth=person.person_id,
                    )
                )

    bench.mentions.sort(key=lambda mention: mention.record_id)
    return bench


def write_files(bench: Benchmark, out_dir: Path) -> list[Path]:
    """Write the benchmark out, for inspection or for a manual run."""
    out_dir.mkdir(parents=True, exist_ok=True)
    roster = out_dir / "roster.csv"
    with open(roster, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["employee_id", "first_name", "last_name", "job_title", "facility", "license_number"]
        )
        for person in bench.people:
            writer.writerow(
                [
                    person.employee_id,
                    person.given,
                    person.family,
                    person.role,
                    person.facility,
                    person.credential,
                ]
            )

    truth = out_dir / "truth.csv"
    with open(truth, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["record_id", "source_role", "written_name", "person_id"])
        for mention in bench.mentions:
            writer.writerow(
                [mention.record_id, mention.source_role, mention.written_name, mention.truth]
            )
    return [roster, truth]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--people", type=int, default=60)
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--out", default=str(REPO_ROOT / "var" / "benchmark"))
    args = parser.parse_args()

    bench = build(args.seed, args.people, args.weeks)
    paths = write_files(bench, Path(args.out))
    print(f"{len(bench.people)} people, {len(bench.mentions)} records")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
