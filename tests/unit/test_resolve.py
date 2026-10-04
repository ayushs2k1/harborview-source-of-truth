"""Identity resolution: features, scoring, and assignment."""

from __future__ import annotations

import pytest

from sot.decisions.store import DecisionSet
from sot.normalize.names import parse_name
from sot.resolve.assign import check_credentials_in_service, check_roster, resolve
from sot.resolve.candidates import PersonIndex
from sot.resolve.features import (
    LEVEL_COMPATIBLE,
    LEVEL_DIFFERENT,
    LEVEL_EXACT,
    LEVEL_INITIAL,
    LEVEL_PHONETIC,
    LEVEL_SAME,
    LEVEL_SIMILAR,
    LEVEL_UNKNOWN,
    LEVEL_VARIANT,
    compare_credential,
    compare_facility,
    compare_first_name,
    compare_last_name,
    compare_role,
    sounds_alike,
)
from sot.resolve.scoring import (
    BAND_AUTO,
    BAND_NONE,
    BAND_REVIEW,
    DECIDED_ANCHOR,
    DECIDED_HUMAN,
    MatchConfig,
    Mention,
    PersonRecord,
    is_ambiguous,
    rank_candidates,
    score_pair,
)


@pytest.fixture()
def config(pack):
    return MatchConfig.from_pack(pack)


def person(name: str, **kwargs) -> PersonRecord:
    parsed = parse_name(name).value
    return PersonRecord(
        person_id=kwargs.pop("person_id", f"P-{parsed.key.replace(' ', '')}"),
        display_name=parsed.display,
        name=parsed,
        **kwargs,
    )


def mention(name: str, **kwargs) -> Mention:
    parsed = parse_name(name).value
    return Mention(
        record_id=kwargs.pop("record_id", f"R-{parsed.key.replace(' ', '')}"),
        source_type=kwargs.pop("source_type", "payroll"),
        source_role=kwargs.pop("source_role", "payroll"),
        display=parsed.display,
        name=parsed,
        **kwargs,
    )


# --- features ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right", "level"),
    [
        ("Ann Abernathy", "Jo Abernathy", LEVEL_EXACT),
        ("Ann ABERNATHY", "Jo abernathy", LEVEL_EXACT),
        ("Ann Abernathy", "Jo Abernathey", LEVEL_SIMILAR),
        ("Ann Smith", "Jo Smyth", LEVEL_PHONETIC),
        ("Ann Abernathy", "Jo Castellanos", LEVEL_DIFFERENT),
    ],
)
def test_family_names_are_compared_by_level(left, right, level, config):
    score = compare_last_name(
        parse_name(left).value,
        parse_name(right).value,
        config.weights,
        similar_threshold=config.last_name_similar,
    )
    assert score.level == level


def test_a_missing_family_name_is_not_evidence_either_way(config):
    score = compare_last_name(None, parse_name("Jo Abernathy").value, config.weights)
    assert score.level == LEVEL_UNKNOWN
    assert score.weight == 0.0


@pytest.mark.parametrize(
    ("left", "right", "level"),
    [
        ("Thomas Lee", "Thomas Ray", LEVEL_EXACT),
        ("Tom Lee", "Thomas Ray", LEVEL_VARIANT),
        ("Thomas Lee", "Thomsa Ray", LEVEL_SIMILAR),
        ("T. Lee", "Thomas Ray", LEVEL_INITIAL),
        ("Thomas Lee", "Priscilla Ray", LEVEL_DIFFERENT),
    ],
)
def test_given_names_are_compared_by_level(left, right, level, config):
    score = compare_first_name(
        parse_name(left).value,
        parse_name(right).value,
        config.weights,
        similar_threshold=config.first_name_similar,
    )
    assert score.level == level


def test_accented_and_unaccented_given_names_are_the_same(config):
    score = compare_first_name(
        parse_name("José Pena").value, parse_name("Jose Pena").value, config.weights
    )
    assert score.level == LEVEL_EXACT


def test_roles_in_one_family_are_compatible(pack, config):
    assert (
        compare_role("RN", "RN", config.weights, families=config.role_families).level == LEVEL_SAME
    )
    assert (
        compare_role("RN", "RN_DON", config.weights, families=config.role_families).level
        == LEVEL_COMPATIBLE
    )
    assert (
        compare_role("RN", "CNA", config.weights, families=config.role_families).level
        == LEVEL_DIFFERENT
    )


def test_a_different_site_is_only_weak_evidence(config):
    """Staff float between sites, so this must not outvote a name."""
    same = compare_facility("BYS", "BYS", config.weights)
    different = compare_facility("BYS", "RVD", config.weights)
    assert abs(different.weight) <= 1.0
    assert same.weight > 0 > different.weight


def test_a_matching_credential_outweighs_everything_else(config):
    """It is issued to one person, so agreement is near-conclusive."""
    score = compare_credential("RN:551203", "RN:551203", config.weights)
    assert (
        score.weight
        > sum(
            abs(config.weights[feature]["exact" if "name" in feature else "same"])
            for feature in ("last_name", "first_name")
        )
        - 0.1
    )


def test_a_credential_only_one_side_records_says_nothing(config):
    assert compare_credential("RN:1", None, config.weights).level == LEVEL_UNKNOWN
    assert compare_credential("RN:1", None, config.weights).weight == 0.0


def test_phonetic_matching_catches_spelling_variants():
    assert sounds_alike("smith", "smyth")
    assert not sounds_alike("abernathy", "castellanos")


# --- scoring ----------------------------------------------------------------


def test_the_specs_worked_example_scores_as_documented(config):
    """Schedule "Marc Bell / CNA / Riverdale" against HR "Marcus Bell / CNA / Riverdale"
    is 6.0 + 3.5 + 1.5 + 1.0 = 12.0, and links automatically."""
    total, features = score_pair(
        mention("Marc Bell", role_code="CNA", facility_code="RVD", source_role="schedule"),
        person("Marcus Bell", role_code="CNA", facility_code="RVD"),
        config,
    )
    assert total == 12.0
    assert config.band_for(total) == BAND_AUTO
    assert [feature.weight for feature in features] == [6.0, 3.5, 1.5, 1.0, 0.0]


def test_a_different_person_scores_below_the_review_band(config):
    total, _ = score_pair(
        mention("Imani Mbeki", role_code="RN", facility_code="BYS"),
        person("Thomas Lindgren", role_code="CNA", facility_code="RVD"),
        config,
    )
    assert config.band_for(total) == BAND_NONE


def test_bands_follow_the_pack(config):
    assert config.band_for(config.auto) == BAND_AUTO
    assert config.band_for(config.auto - 0.01) == BAND_REVIEW
    assert config.band_for(config.review - 0.01) == BAND_NONE


def test_candidates_come_back_best_first_with_a_stable_tiebreak(config):
    people = [
        person("Thomas Lindgren", person_id="P-B"),
        person("Thomas Lindgren", person_id="P-A"),
        person("Imani Mbeki", person_id="P-C"),
    ]
    ranked = rank_candidates(mention("Thomas Lindgren"), people, config)
    assert [candidate.person_id for candidate in ranked[:2]] == ["P-A", "P-B"]


def test_two_equally_good_candidates_are_ambiguous(config):
    people = [
        person("Thomas Lindgren", person_id="P-A"),
        person("Thomas Lindgren", person_id="P-B"),
    ]
    ranked = rank_candidates(mention("Thomas Lindgren"), people, config)
    assert is_ambiguous(ranked, config)


def test_a_clear_winner_is_not_ambiguous(config):
    people = [
        person("Thomas Lindgren", person_id="P-A", role_code="RN", facility_code="BYS"),
        person("Imani Mbeki", person_id="P-B"),
    ]
    ranked = rank_candidates(
        mention("Thomas Lindgren", role_code="RN", facility_code="BYS"), people, config
    )
    assert not is_ambiguous(ranked, config)


def test_a_single_candidate_is_never_ambiguous(config):
    ranked = rank_candidates(mention("Thomas Lindgren"), [person("Thomas Lindgren")], config)
    assert not is_ambiguous(ranked, config)


# --- blocking ---------------------------------------------------------------


def test_a_small_roster_is_compared_in_full(config):
    index = PersonIndex([person("Thomas Lindgren"), person("Imani Mbeki")], config)
    assert not index.blocking
    assert len(index.candidates(mention("Someone Else"))) == 2


def test_a_large_roster_is_narrowed_but_keeps_the_true_match(pack):
    """The keys exist so that a true match survives at least one of them."""
    import dataclasses

    config = dataclasses.replace(MatchConfig.from_pack(pack), max_persons_without_blocking=5)
    people = [
        person(f"Person{index} Surname{index}", person_id=f"P-{index:03d}") for index in range(50)
    ]
    target = person("Thomas Lindgren", person_id="P-T", role_code="RN", facility_code="BYS")
    index = PersonIndex([*people, target], config)
    assert index.blocking

    # Misspelled surname: caught by the phonetic key.
    found = index.candidates(mention("Thomas Lindgrenn", role_code="RN", facility_code="BYS"))
    assert target in found
    # Completely different surname: caught by site and role.
    found = index.candidates(mention("Thomas Married", role_code="RN", facility_code="BYS"))
    assert target in found


def test_blocking_always_includes_the_credential_holder(pack):
    import dataclasses

    config = dataclasses.replace(MatchConfig.from_pack(pack), max_persons_without_blocking=1)
    target = person("Thomas Lindgren", person_id="P-T", credential_key="RN:1")
    index = PersonIndex([target, person("Imani Mbeki", person_id="P-O")], config)
    assert target in index.candidates(mention("Totally Different", credential_key="RN:1"))


# --- roster checks ----------------------------------------------------------


def test_one_employee_number_on_two_people_is_critical():
    findings = check_roster(
        [
            person("Thomas Lindgren", person_id="P-1", employee_id="E1"),
            person("Imani Mbeki", person_id="P-2", employee_id="E1"),
        ]
    )
    assert [finding.code for finding in findings] == ["EMPLOYEE_ID_COLLISION"]


def test_the_same_person_under_two_numbers_is_a_duplicate():
    findings = check_roster(
        [
            person("Thomas Lindgren", person_id="P-1", employee_id="E1", phone_key="7185550001"),
            person("Thomas Lindgren", person_id="P-2", employee_id="E2", phone_key="7185550001"),
        ]
    )
    assert "DUPLICATE_PERSON_HR" in [finding.code for finding in findings]


def test_two_different_people_sharing_a_phone_is_only_a_warning():
    findings = check_roster(
        [
            person("Thomas Lindgren", person_id="P-1", phone_key="7185550001"),
            person("Imani Mbeki", person_id="P-2", phone_key="7185550001"),
        ]
    )
    assert [finding.code for finding in findings] == ["SHARED_PHONE"]


def test_one_credential_on_two_people_is_critical():
    findings = check_roster(
        [
            person("Thomas Lindgren", person_id="P-1", credential_key="RN:1"),
            person("Imani Mbeki", person_id="P-2", credential_key="RN:1"),
        ]
    )
    assert "LICENSE_NUMBER_SHARED" in [finding.code for finding in findings]


def test_a_clean_roster_raises_nothing():
    assert check_roster([person("Thomas Lindgren"), person("Imani Mbeki")]) == []


def test_a_roster_credential_the_service_has_never_heard_of_is_flagged():
    findings = check_credentials_in_service(
        [person("Thomas Lindgren", person_id="P-1", credential_key="RN:999")], {"RN:1"}
    )
    assert [finding.code for finding in findings] == ["LICENSE_NOT_IN_SERVICE"]


def test_nothing_is_flagged_when_no_credential_source_was_supplied():
    """Otherwise everybody is flagged for the absence of a file nobody sent."""
    assert (
        check_credentials_in_service([person("Thomas Lindgren", credential_key="RN:999")], set())
        == []
    )


# --- assignment -------------------------------------------------------------


def test_a_confident_match_links_automatically(config):
    people = [person("Marcus Bell", person_id="P-1", role_code="CNA", facility_code="RVD")]
    result = resolve(
        people,
        [mention("Marc Bell", role_code="CNA", facility_code="RVD", source_role="schedule")],
        config,
    )
    assert len(result.links) == 1
    assert result.links[0].person_id == "P-1"
    assert result.links[0].band == BAND_AUTO


def test_a_link_keeps_the_reasoning_that_produced_it(config):
    """The person page renders this as a waterfall, and "why" is the whole question."""
    people = [person("Marcus Bell", person_id="P-1", role_code="CNA", facility_code="RVD")]
    result = resolve(people, [mention("Marc Bell", role_code="CNA", facility_code="RVD")], config)
    explanation = result.links[0].explanation
    assert explanation["total"] == 12.0
    assert {feature["feature"] for feature in explanation["features"]} == {
        "last_name",
        "first_name",
        "role",
        "facility",
        "credential",
    }
    assert any(feature["level"] == "variant" for feature in explanation["features"])


def test_a_credential_number_links_without_scoring(config):
    """The anchor runs before the matcher, and a changed surname does not stop it."""
    people = [person("Thomas Lindgren", person_id="P-1", credential_key="RN:551203")]
    result = resolve(
        people,
        [
            mention(
                "Thomas Abernathy",
                credential_key="RN:551203",
                source_role="credentials",
                source_type="licenses",
            )
        ],
        config,
    )
    assert result.links[0].decided_by == DECIDED_ANCHOR
    assert "NAME_MISMATCH_LICENSE" in result.codes()


def test_an_anchored_link_with_a_matching_name_raises_nothing(config):
    people = [person("Thomas Lindgren", person_id="P-1", credential_key="RN:551203")]
    result = resolve(
        people,
        [mention("Thomas Lindgren", credential_key="RN:551203", source_role="credentials")],
        config,
    )
    assert result.codes() == []


def test_a_borderline_match_is_put_to_a_human_rather_than_guessed(config):
    people = [person("Marcus Bell", person_id="P-1", role_code="CNA", facility_code="RVD")]
    result = resolve(people, [mention("M. Bell", role_code="CNA", facility_code="BYS")], config)
    assert "MATCH_REVIEW" in result.codes()
    assert all(link.person_id != "P-1" for link in result.links)


def test_two_equally_good_candidates_are_left_alone(config):
    people = [
        person("Thomas Lindgren", person_id="P-1", role_code="RN", facility_code="BYS"),
        person("Thomas Lindgren", person_id="P-2", role_code="RN", facility_code="BYS"),
    ]
    result = resolve(
        people, [mention("Thomas Lindgren", role_code="RN", facility_code="BYS")], config
    )
    assert "MATCH_AMBIGUOUS" in result.codes()


def test_a_human_decision_overrides_the_score(config):
    """Somebody already answered this; the matcher does not get a second opinion."""
    people = [
        person("Thomas Lindgren", person_id="P-1"),
        person("Imani Mbeki", person_id="P-2"),
    ]
    item = mention("Thomas Lindgren")
    decisions = DecisionSet(accepted={item.fingerprint: "P-2"})
    result = resolve(people, [item], config, decisions=decisions)
    assert result.links[0].person_id == "P-2"
    assert result.links[0].decided_by == DECIDED_HUMAN


def test_a_rejected_pair_is_never_linked(config):
    people = [person("Thomas Lindgren", person_id="P-1", role_code="RN", facility_code="BYS")]
    item = mention("Thomas Lindgren", role_code="RN", facility_code="BYS")
    decisions = DecisionSet(rejected={(item.fingerprint, "P-1")})
    result = resolve(people, [item], config, decisions=decisions)
    assert all(link.person_id != "P-1" for link in result.links)
    assert "UNMATCHED_PAYROLL" in result.codes()


def test_an_unmatched_record_becomes_a_person_rather_than_disappearing(config):
    """A nurse who is paid but is in no other system is the most interesting thing
    this system can find, and she only stays visible if she has somewhere to be."""
    result = resolve([person("Thomas Lindgren", person_id="P-1")], [mention("Nobody Here")], config)
    provisional = [item for item in result.persons if item.status == "provisional"]
    assert len(provisional) == 1
    assert provisional[0].display_name == "Nobody Here"
    assert result.links[0].person_id == provisional[0].person_id


def test_one_unknown_person_in_two_sources_becomes_one_provisional_person(config):
    result = resolve(
        [],
        [
            mention("Nobody Here", record_id="R1", source_role="payroll"),
            mention("Nobody Here", record_id="R2", source_role="schedule", source_type="schedule"),
        ],
        config,
    )
    assert len([item for item in result.persons if item.status == "provisional"]) == 1
    assert {"UNMATCHED_PAYROLL", "UNMATCHED_SCHEDULE"} <= set(result.codes())


def test_two_payroll_rows_for_one_person_and_period_are_a_possible_double_payment(config):
    people = [person("Marcus Bell", person_id="P-1", role_code="CNA", facility_code="RVD")]
    rows = [
        mention(
            "Marcus Bell",
            record_id="R1",
            role_code="CNA",
            facility_code="RVD",
            scope=("2026-09-14", "CNA", "RVD"),
            label="P-1",
        ),
        mention(
            "Marcus Bell",
            record_id="R2",
            role_code="CNA",
            facility_code="RVD",
            scope=("2026-09-14", "CNA", "RVD"),
            label="P-2",
        ),
    ]
    result = resolve(people, rows, config)
    assert "DUPLICATE_PAY_PERIOD" in result.codes()
    assert len(result.links) == 2, "both rows stay linked; the payment is the finding"


def test_a_look_alike_is_reassigned_rather_than_called_a_duplicate(config):
    """Two rows claiming one slot where the second genuinely belongs to somebody else."""
    people = [
        person("Thomas Lindgren", person_id="P-1", role_code="RN", facility_code="BYS"),
        person("Thomas Abernathy", person_id="P-2", role_code="RN", facility_code="BYS"),
    ]
    rows = [
        mention(
            "Thomas Lindgren",
            record_id="R1",
            role_code="RN",
            facility_code="BYS",
            scope=("w1", "RN", "BYS"),
        ),
        mention(
            "Thomas Abernathy",
            record_id="R2",
            role_code="RN",
            facility_code="BYS",
            scope=("w1", "RN", "BYS"),
        ),
    ]
    result = resolve(people, rows, config)
    assert {link.person_id for link in result.links} == {"P-1", "P-2"}
    assert "DUPLICATE_PAY_PERIOD" not in result.codes()


def test_two_rota_rows_for_one_person_on_one_page_are_flagged(config):
    people = [person("Marcus Bell", person_id="P-1", role_code="CNA", facility_code="RVD")]
    rows = [
        mention(
            "Marcus Bell",
            record_id="R1",
            role_code="CNA",
            facility_code="RVD",
            source_role="schedule",
            source_type="schedule",
            scope=("F", 1),
        ),
        mention(
            "Marc Bell",
            record_id="R2",
            role_code="CNA",
            facility_code="RVD",
            source_role="schedule",
            source_type="schedule",
            scope=("F", 1),
        ),
    ]
    result = resolve(people, rows, config)
    assert "DUPLICATE_SCHEDULE_ROW" in result.codes()


def test_resolution_does_not_depend_on_the_order_records_arrive(config):
    people = [
        person("Thomas Lindgren", person_id="P-1", role_code="RN", facility_code="BYS"),
        person("Imani Mbeki", person_id="P-2", role_code="CNA", facility_code="RVD"),
    ]
    rows = [
        mention("Thomas Lindgren", record_id="R1", role_code="RN", facility_code="BYS"),
        mention("Imani Mbeki", record_id="R2", role_code="CNA", facility_code="RVD"),
        mention("Nobody Here", record_id="R3"),
    ]

    def summary(order):
        result = resolve(people, order, config)
        return (
            sorted((link.record_id, link.person_id, link.score) for link in result.links),
            sorted(result.codes()),
            sorted(item.person_id for item in result.persons),
        )

    assert summary(rows) == summary(list(reversed(rows)))
