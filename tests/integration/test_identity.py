"""Identity resolution against the fixtures and against a measured benchmark.

Ten people cannot tell you whether a matcher works, so the accuracy test runs against
a seeded synthetic roster of sixty with known ground truth. The spec's target is
precision at or above 0.98 on automatic links, and precision is the number that
matters: a missed link becomes a visible flag, while a wrong one quietly pays the
wrong person.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from sot.ids import record_fingerprint
from sot.ingest.service import ingest_paths
from sot.normalize.names import parse_name
from sot.resolve.assign import resolve
from sot.resolve.scoring import BAND_AUTO, MatchConfig, Mention, PersonRecord
from sot.store.db import Database

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

AS_OF = date(2026, 9, 21)


@pytest.fixture()
def run(tmp_path: Path):
    database = Database(tmp_path / "identity.duckdb")

    def ingest(target, **kwargs):
        return ingest_paths(target, pack_id="healthcare_ny", as_of=AS_OF, db=database, **kwargs)

    ingest.db = database  # type: ignore[attr-defined]
    yield ingest
    database.close()


# --- the fixtures -----------------------------------------------------------


def test_every_clean_record_links_to_a_real_person(run, sample_dir):
    """Phase 4's exit criterion. Nothing in the clean set should need a human."""
    result = run(sample_dir / "clean")
    resolution = result.resolution

    assert [item for item in resolution.persons if item.status == "provisional"] == []
    assert len(resolution.persons) == 10
    assert all(link.person_id.startswith("P-E") for link in resolution.links)
    assert resolution.codes() == []


def test_the_clean_run_links_every_source(run, sample_dir):
    result = run(sample_dir / "clean")
    by_source: dict[str, int] = {}
    for link in result.resolution.links:
        by_source[link.source_type] = by_source.get(link.source_type, 0) + 1
    assert by_source == {"payroll": 11, "licenses": 10, "schedule": 11}


def test_credentials_link_on_their_number_not_their_spelling(run, sample_dir):
    result = run(sample_dir / "clean")
    anchored = [link for link in result.resolution.links if link.decided_by == "anchor"]
    assert len(anchored) == 10


def test_a_shortened_name_on_the_rota_links_without_asking(run, sample_dir):
    """The brief's own example: one person, two spellings, no human needed."""
    result = run(sample_dir / "clean")
    schedule_links = [link for link in result.resolution.links if link.source_type == "schedule"]
    assert all(link.band == BAND_AUTO for link in schedule_links)
    assert all(link.score >= 8.0 for link in schedule_links)


def test_a_float_links_to_one_person_from_both_pages(run, sample_dir):
    result = run(sample_dir / "clean")
    rows = run.db.query(
        "SELECT person_id, facility_code, count(*) AS n FROM shift_segments "
        "WHERE run_id = ? GROUP BY person_id, facility_code ORDER BY person_id",
        [result.run_id],
    )
    sites_per_person: dict[str, set[str]] = {}
    for row in rows:
        sites_per_person.setdefault(row["person_id"], set()).add(row["facility_code"])
    floats = {pid: sites for pid, sites in sites_per_person.items() if len(sites) > 1}
    assert len(floats) == 1


def test_the_messy_set_finds_the_ghost_and_the_agency_nurse(run, sample_dir):
    result = run(sample_dir / "messy")
    codes = set(result.resolution.codes())
    assert {"UNMATCHED_PAYROLL", "UNMATCHED_SCHEDULE", "DUPLICATE_PAY_PERIOD"} <= codes


def test_unknown_people_are_kept_as_provisional_persons(run, sample_dir):
    result = run(sample_dir / "messy")
    provisional = sorted(
        item.display_name for item in result.resolution.persons if item.status == "provisional"
    )
    assert provisional == ["L. Okonkwo", "Miguel Torres"]


def test_an_unknown_nurse_on_the_rota_is_critical_not_a_note(run, sample_dir):
    """The role needs a licence, so somebody unaccounted for is a compliance problem."""
    result = run(sample_dir / "messy")
    flag = next(f for f in result.flags if f.rule_code == "UNMATCHED_SCHEDULE")
    assert flag.severity.value == "CRITICAL"


def test_resolved_people_are_written_back_onto_their_records(run, sample_dir):
    result = run(sample_dir / "clean")
    unlinked_records = run.db.scalar(
        "SELECT count(*) FROM std_records WHERE run_id = ? AND person_id IS NULL",
        [result.run_id],
    )
    unlinked_segments = run.db.scalar(
        "SELECT count(*) FROM shift_segments WHERE run_id = ? AND person_id IS NULL",
        [result.run_id],
    )
    # 48 records: 10 roster, 11 payroll and 10 credentials are about people and
    # carry a person; the 14 census days and 3 vendor documents are not.
    assert unlinked_records == 17
    assert (
        run.db.scalar(
            "SELECT count(*) FROM std_records WHERE run_id = ? AND person_id IS NOT NULL",
            [result.run_id],
        )
        == 31
    )
    assert unlinked_segments == 0


def test_links_and_people_are_stored_with_their_reasoning(run, sample_dir):
    result = run(sample_dir / "clean")
    assert run.db.scalar("SELECT count(*) FROM persons WHERE run_id = ?", [result.run_id]) == 10
    row = run.db.query_one(
        "SELECT explanation_json, score, band, decided_by FROM links "
        "WHERE run_id = ? AND source_type = 'schedule' LIMIT 1",
        [result.run_id],
    )
    assert "features" in row["explanation_json"]
    assert row["band"] == "auto"


# --- measured accuracy ------------------------------------------------------


def _benchmark_inputs(bench):
    people = [
        PersonRecord(
            person_id=item.person_id,
            display_name=item.full,
            name=parse_name(item.full).value,
            role_code=item.role,
            facility_code=item.facility,
            credential_key=f"{item.role}:{item.credential.split('-')[-1]}"
            if item.credential
            else None,
            employee_id=item.employee_id,
        )
        for item in bench.people
    ]
    mentions = []
    for item in bench.mentions:
        name = parse_name(item.written_name).value
        mentions.append(
            Mention(
                record_id=item.record_id,
                source_type=item.source_role,
                source_role=item.source_role,
                display=item.written_name,
                name=name,
                role_code=item.role or None,
                facility_code=item.facility or None,
                credential_key=(
                    f"{item.role}:{item.credential.split('-')[-1]}" if item.credential else None
                ),
                fingerprint=record_fingerprint(
                    item.source_role, name.key if name else "", item.role, item.facility
                ),
                scope=(item.record_id.split("-")[1], item.role, item.facility),
            )
        )
    return people, mentions


@pytest.fixture(scope="module")
def measured(request):
    import gen_identity_benchmark

    from sot.ingest.contracts import load_pack

    bench = gen_identity_benchmark.build(seed=42, people_count=60, weeks=4)
    pack = load_pack("healthcare_ny", packs_dir=str(REPO_ROOT / "packs"))
    people, mentions = _benchmark_inputs(bench)
    result = resolve(people, mentions, MatchConfig.from_pack(pack))

    truth = bench.truth
    auto = [link for link in result.links if link.band == BAND_AUTO]
    correct = [link for link in auto if truth.get(link.record_id) == link.person_id]
    return {
        "bench": bench,
        "result": result,
        "auto": auto,
        "correct": correct,
        "precision": len(correct) / len(auto) if auto else 0.0,
        "recall": len(correct) / len(mentions) if mentions else 0.0,
        "mentions": mentions,
    }


def test_the_benchmark_is_large_enough_to_mean_something(measured):
    assert len(measured["bench"].people) == 60
    assert len(measured["mentions"]) >= 500


def test_automatic_links_are_precise(measured):
    """The spec's target. A wrong auto-link quietly pays the wrong person, so this is
    the number that has to hold."""
    wrong = [
        (link.record_id, link.person_id, measured["bench"].truth.get(link.record_id))
        for link in measured["auto"]
        if measured["bench"].truth.get(link.record_id) != link.person_id
    ]
    assert measured["precision"] >= 0.98, (
        f"precision {measured['precision']:.3f}, wrong: {wrong[:5]}"
    )


def test_recall_is_high_enough_to_be_useful(measured):
    """Recall matters less than precision - a missed link becomes a visible flag - but
    a matcher that links nothing would be perfectly precise and perfectly useless."""
    assert measured["recall"] >= 0.85, f"recall {measured['recall']:.3f}"


def test_everything_not_linked_automatically_is_visible(measured):
    """Nothing may be silently dropped: every record is either linked or flagged."""
    result = measured["result"]
    linked = {link.record_id for link in result.links}
    assert linked == {mention.record_id for mention in measured["mentions"]}


def test_the_benchmark_is_reproducible():
    import gen_identity_benchmark

    first = gen_identity_benchmark.build(seed=42)
    second = gen_identity_benchmark.build(seed=42)
    assert [item.written_name for item in first.mentions] == [
        item.written_name for item in second.mentions
    ]
