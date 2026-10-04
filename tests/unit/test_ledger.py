"""The claims ledger and golden records."""

from __future__ import annotations

from datetime import date

import pytest

from sot.ledger.authority import Authority, authority_for_pack, load_authority
from sot.ledger.claims import Claim, claims_from_records, claims_from_segments, credential_entity_id
from sot.ledger.golden import build_credentials, conflict_findings, credential_holders, survive


def claim(attribute: str, value: str, role: str, **kwargs) -> Claim:
    return Claim(
        entity_type=kwargs.pop("entity_type", "person"),
        entity_id=kwargs.pop("entity_id", "P-1"),
        attribute=attribute,
        value_norm=value,
        source_type=kwargs.pop("source_type", role),
        source_role=role,
        **kwargs,
    )


def record(record_id: str, payload: dict, **kwargs) -> dict:
    import json

    return {
        "record_id": record_id,
        "source_type": kwargs.pop("source_type", "hr"),
        "file_id": kwargs.pop("file_id", "FL-1"),
        "row_index": kwargs.pop("row_index", 2),
        "payload_json": json.dumps(payload),
        "raw_json": json.dumps(kwargs.pop("raw", {})),
        "quality_json": json.dumps(kwargs.pop("quality", {})),
    }


# --- claims -----------------------------------------------------------------


def test_a_claim_keeps_where_it_came_from():
    """Principle 2. A flag is only useful if it can point at the characters."""
    claims = claims_from_records(
        [record("R1", {"first_name": "Ann", "last_name": "Abernathy", "hire_date": "2020-03-02"})],
        source_role="roster",
        person_by_record={"R1": "P-1"},
    )
    hire = next(item for item in claims if item.attribute == "hire_date")
    assert hire.value_norm == "2020-03-02"
    assert hire.locator == {"row": 2, "column": "hire_date"}
    assert hire.file_id == "FL-1"


def test_a_claim_id_is_stable_across_runs():
    first = claim("phone", "7185550001", "roster", file_id="FL-1", locator={"row": 2})
    second = claim("phone", "7185550001", "roster", file_id="FL-1", locator={"row": 2})
    assert first.claim_id == second.claim_id


def test_a_different_value_is_a_different_claim():
    first = claim("phone", "7185550001", "roster")
    second = claim("phone", "7185550002", "roster")
    assert first.claim_id != second.claim_id


def test_credential_facts_belong_to_the_credential_not_the_person():
    """HR's copy and the service's record of one licence must land on one entity, or
    their disagreement becomes two credentials instead of a finding."""
    claims = claims_from_records(
        [
            record(
                "R1",
                {
                    "license_number": "RN-1",
                    "license_number__key": "RN:1",
                    "expiration_date": "2027-05-31",
                    "name_on_license": "Ann Abernathy",
                },
                source_type="licenses",
            )
        ],
        source_role="credentials",
        person_by_record={"R1": "P-1"},
    )
    expiry = next(item for item in claims if item.attribute == "credential_expires_on")
    assert expiry.entity_type == "credential"
    assert expiry.entity_id == credential_entity_id("RN:1")


def test_hr_and_the_service_claim_the_same_credential_entity():
    roster = claims_from_records(
        [
            record(
                "R1",
                {
                    "license_number": "RN-1",
                    "license_number__key": "RN:1",
                    "license_expiration": "2027-05-31",
                },
            )
        ],
        source_role="roster",
        person_by_record={"R1": "P-1"},
    )
    service = claims_from_records(
        [
            record(
                "R2",
                {
                    "license_number": "RN-1",
                    "license_number__key": "RN:1",
                    "expiration_date": "2027-07-31",
                },
                source_type="licenses",
            )
        ],
        source_role="credentials",
        person_by_record={"R2": "P-1"},
    )
    entities = {
        item.entity_id for item in (*roster, *service) if item.attribute == "credential_expires_on"
    }
    assert len(entities) == 1


def test_the_date_a_source_vouches_for_is_recorded():
    """A credential verified last week beats the same field copied into HR years ago,
    which is only decidable if each claim carries its own date."""
    credentials = claims_from_records(
        [
            record(
                "R1",
                {"license_number__key": "RN:1", "last_verified": "2026-09-01"},
                source_type="licenses",
            )
        ],
        source_role="credentials",
        person_by_record={"R1": "P-1"},
    )
    assert all(item.observed_on == date(2026, 9, 1) for item in credentials)

    payroll = claims_from_records(
        [
            record(
                "R2",
                {"employee_name": "Ann Abernathy", "period_end": "2026-09-20", "hours_paid": "36"},
                source_type="payroll",
            )
        ],
        source_role="payroll",
        person_by_record={"R2": "P-1"},
    )
    assert all(item.observed_on == date(2026, 9, 20) for item in payroll)


def test_the_rota_claims_each_fact_once_not_once_per_cell():
    """Forty identical claims would drown the evidence list."""
    segments = [
        {
            "person_id": "P-1",
            "facility_code": "BYS",
            "role_code": "RN",
            "work_date": date(2026, 9, 14 + offset),
            "segment_id": f"S{offset}",
            "person_ref": "Ann Abernathy",
            "file_id": "FL-1",
            "page": 1,
            "row_index": 2,
            "column_header": "Mon",
            "source_type": "schedule",
        }
        for offset in range(5)
    ]
    claims = claims_from_segments(segments)
    assert len([item for item in claims if item.attribute == "worked_facility"]) == 1


def test_a_record_with_no_person_makes_no_person_claims():
    claims = claims_from_records(
        [record("R1", {"hire_date": "2020-01-01"})], source_role="roster", person_by_record={}
    )
    assert claims == []


# --- authority --------------------------------------------------------------


def test_the_pack_authority_loads(pack):
    authority = authority_for_pack(pack)
    assert authority.order_for("credential_expires_on")[0] == "credentials"
    assert authority.order_for("hire_date") == ("roster",)
    assert authority.conflict_within["credential_expires_on"] == "HR_LICENSE_EXPIRY_STALE"


def test_a_missing_authority_file_gives_defaults(tmp_path):
    authority = load_authority(tmp_path / "nothing.yaml")
    assert authority.order_for("anything") == authority.default_order


def test_an_unlisted_source_sorts_last():
    authority = Authority(orders={"phone": ("roster",)})
    assert authority.rank("phone", "roster") < authority.rank("phone", "payroll")


# --- survivorship -----------------------------------------------------------


def test_the_authoritative_source_wins():
    """The verification service beats HR's copy of an expiry. That is the whole point
    of comparing the two."""
    golden = survive(
        [
            claim("credential_expires_on", "2027-05-31", "roster"),
            claim("credential_expires_on", "2027-07-31", "credentials"),
        ],
        Authority(orders={"credential_expires_on": ("credentials", "roster")}),
    )
    value = golden.get("person", "P-1", "credential_expires_on")
    assert value.value_norm == "2027-07-31"
    assert "source authority" in value.rule


def test_the_losing_claim_is_kept_not_discarded():
    golden = survive(
        [
            claim("credential_expires_on", "2027-05-31", "roster"),
            claim("credential_expires_on", "2027-07-31", "credentials"),
        ],
        Authority(orders={"credential_expires_on": ("credentials", "roster")}),
    )
    value = golden.get("person", "P-1", "credential_expires_on")
    assert value.conflict_count == 1
    assert [other.value_norm for other in value.others] == ["2027-05-31"]


def test_equal_sources_are_settled_by_the_later_observation():
    golden = survive(
        [
            claim("phone", "7185550001", "roster", observed_on=date(2024, 1, 1)),
            claim("phone", "7185550002", "roster", observed_on=date(2026, 1, 1)),
        ],
        Authority(orders={"phone": ("roster",)}),
    )
    assert golden.person("P-1", "phone") == "7185550002"


def test_a_populated_value_beats_an_empty_one():
    golden = survive(
        [claim("email", "", "roster"), claim("email", "a@example.test", "roster")],
        Authority(orders={"email": ("roster",)}),
    )
    assert golden.person("P-1", "email") == "a@example.test"


def test_agreement_is_not_a_conflict():
    golden = survive(
        [claim("phone", "7185550001", "roster"), claim("phone", "7185550001", "credentials")],
        Authority(),
    )
    value = golden.get("person", "P-1", "phone")
    assert value.candidate_count == 2
    assert value.conflict_count == 0


def test_survivorship_does_not_depend_on_claim_order():
    claims = [
        claim("phone", "7185550001", "roster"),
        claim("phone", "7185550002", "payroll"),
        claim("phone", "7185550003", "credentials"),
    ]
    authority = Authority()
    forward = survive(claims, authority).person("P-1", "phone")
    backward = survive(list(reversed(claims)), authority).person("P-1", "phone")
    assert forward == backward


def test_a_within_attribute_conflict_raises_the_configured_rule():
    authority = Authority(
        orders={"credential_expires_on": ("credentials", "roster")},
        conflict_within={"credential_expires_on": "HR_LICENSE_EXPIRY_STALE"},
    )
    golden = survive(
        [
            claim(
                "credential_expires_on",
                "2027-05-31",
                "roster",
                entity_type="credential",
                entity_id="CR-1",
            ),
            claim(
                "credential_expires_on",
                "2027-07-31",
                "credentials",
                entity_type="credential",
                entity_id="CR-1",
            ),
        ],
        authority,
    )
    findings = conflict_findings(
        golden,
        authority,
        display_names={"P-1": "Ann Abernathy"},
        credential_holders={"CR-1": "P-1"},
    )
    assert [finding.code for finding in findings] == ["HR_LICENSE_EXPIRY_STALE"]
    assert findings[0].params["service_date"] == "2027-07-31"
    assert findings[0].params["hr_date"] == "2027-05-31"


# --- derived entities -------------------------------------------------------


def test_a_credential_knows_whether_the_service_has_it():
    claims = [
        claim("credential_number", "RN-1", "roster", entity_type="credential", entity_id="CR-1"),
        claim(
            "credential_expires_on",
            "2027-05-31",
            "roster",
            entity_type="credential",
            entity_id="CR-1",
        ),
    ]
    golden = survive(claims, Authority())
    credentials = build_credentials(golden, {"CR-1": "P-1"}, claims)
    assert len(credentials) == 1
    assert not credentials[0].in_service, "HR alone is not verification"


@pytest.mark.parametrize(
    ("when", "expected"),
    [(date(2026, 1, 1), True), (date(2027, 5, 31), True), (date(2027, 6, 1), False)],
)
def test_a_credential_knows_which_dates_it_covers(when: date, expected: bool):
    claims = [
        claim(
            "credential_expires_on",
            "2027-05-31",
            "credentials",
            entity_type="credential",
            entity_id="CR-1",
        ),
    ]
    credential = build_credentials(survive(claims, Authority()), {"CR-1": "P-1"}, claims)[0]
    assert credential.valid_on(when) is expected


def test_an_unknown_expiry_makes_validity_unknown_not_false():
    claims = [
        claim("credential_type", "RN", "credentials", entity_type="credential", entity_id="CR-1")
    ]
    credential = build_credentials(survive(claims, Authority()), {"CR-1": "P-1"}, claims)[0]
    assert credential.valid_on(date(2026, 1, 1)) is None


def test_the_holder_comes_from_the_records_that_name_the_number():
    holders = credential_holders([record("R1", {"license_number__key": "RN:1"})], {"R1": "P-1"})
    assert holders == {credential_entity_id("RN:1"): "P-1"}
