"""The claims ledger.

Spec principle 2: never overwrite. Every value every source gave us is stored as its
own claim, with the file, row and column it came from and the date the source vouches
for it. Nothing is merged on the way in.

That is what "every number has receipts" means in practice. A golden record is a
*view* over the ledger - a decision about which claim to display - and the claims it
did not pick are still there, which is how the person page can show that HR and the
verification service disagree rather than quietly siding with one.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sot.canon import canonical_json
from sot.ids import stable_id

ENTITY_PERSON = "person"
ENTITY_CREDENTIAL = "credential"
ENTITY_FACILITY = "facility"
ENTITY_ORG = "org"

#: Canonical field -> claim attribute, per source role. The engine's own vocabulary:
#: a pack maps its columns onto the canonical names, and this maps those onto the
#: facts the ledger records.
FIELD_ATTRIBUTES: dict[str, dict[str, str]] = {
    "roster": {
        "employee_id": "employee_id",
        "hire_date": "hire_date",
        "termination_date": "termination_date",
        "status": "employment_status",
        "phone": "phone",
        "email": "email",
        "facility": "home_facility",
        "facility_code": "home_facility",
        "job_title": "job_title",
        "job_code": "job_title",
        # HR's own copy of the expiry. Claimed against the credential so that it sits
        # beside the verification service's, which is the only way the two can be
        # seen to disagree.
        "license_expiration": "credential_expires_on",
    },
    "credentials": {
        "license_type": "credential_type",
        "expiration_date": "credential_expires_on",
        "last_verified": "credential_last_verified",
        "issue_date": "credential_issued_on",
        "status": "credential_status",
        "state": "credential_state",
    },
    "payroll": {
        "hours_paid": "paid_hours",
        "period_start": "pay_period_start",
        "period_end": "pay_period_end",
        "job_code": "paid_role",
        "facility_code": "paid_facility",
    },
}

#: Attributes that belong to the credential rather than the person holding it.
CREDENTIAL_ATTRIBUTES = frozenset(
    {
        "credential_number",
        "credential_type",
        "credential_expires_on",
        "credential_last_verified",
        "credential_issued_on",
        "credential_status",
        "credential_state",
        "name_on_credential",
    }
)


@dataclass(frozen=True)
class Claim:
    """One source's statement about one attribute of one entity."""

    entity_type: str
    entity_id: str
    attribute: str
    value_norm: str
    source_type: str
    source_role: str
    value_raw: str = ""
    file_id: str = ""
    locator: Mapping[str, Any] = field(default_factory=dict)
    observed_on: date | None = None
    quality: str = "ok"

    @property
    def claim_id(self) -> str:
        """Stable across runs: the same cell in the same file is the same claim."""
        return stable_id(
            "CL",
            {
                "entity": f"{self.entity_type}:{self.entity_id}",
                "attribute": self.attribute,
                "source": self.source_type,
                "file": self.file_id,
                "locator": dict(self.locator),
                "value": self.value_norm,
            },
        )

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "claim_id": self.claim_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "attribute": self.attribute,
            "value_raw": self.value_raw,
            "value_norm": self.value_norm,
            "source_type": self.source_type,
            "file_id": self.file_id,
            "locator_json": canonical_json(dict(self.locator)),
            "observed_on": self.observed_on,
            "quality": self.quality,
        }


def credential_entity_id(number_key: str) -> str:
    """Identity of a credential, from its type and digits.

    Keyed on the number rather than on the holder, so HR's copy and the verification
    service's record of the same licence land on one entity and their disagreement
    becomes visible instead of becoming two credentials.
    """
    return stable_id("CR", {"key": number_key.upper()})


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _payload(record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(record.get("payload_json") or "{}")
    except (TypeError, ValueError):
        return {}


def _raw(record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(record.get("raw_json") or "{}")
    except (TypeError, ValueError):
        return {}


def _quality(record: Mapping[str, Any]) -> dict[str, str]:
    try:
        return json.loads(record.get("quality_json") or "{}")
    except (TypeError, ValueError):
        return {}


def _raw_value(raw: Mapping[str, Any], field_name: str) -> str:
    """Best effort at the original text behind a canonical field.

    The raw row is keyed by the heading the file used, which is usually but not always
    the canonical name. An exact match is preferred; otherwise the raw row is left out
    rather than guessed at, since the point of the raw value is that it is verbatim.
    """
    if field_name in raw:
        return str(raw[field_name])
    for heading, value in raw.items():
        if str(heading).strip().lower().replace(" ", "_") == field_name:
            return str(value)
    return ""


def claims_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    source_role: str,
    person_by_record: Mapping[str, str],
) -> list[Claim]:
    """Every claim a set of standardized records makes."""
    claims: list[Claim] = []
    for record in records:
        claims.extend(
            _claims_for_record(
                record,
                source_role=source_role,
                person_id=person_by_record.get(str(record.get("record_id") or "")),
            )
        )
    return claims


def _claims_for_record(
    record: Mapping[str, Any], *, source_role: str, person_id: str | None
) -> list[Claim]:
    """Every claim one standardized row makes."""
    payload = _payload(record)
    raw = _raw(record)
    qualities = _quality(record)
    file_id = str(record.get("file_id") or "")
    row_index = record.get("row_index")
    source_type = str(record.get("source_type") or source_role)
    observed_on = _observed_on(source_role, payload)

    number_key = str(payload.get("license_number__key") or "").strip()
    credential_id = credential_entity_id(number_key) if number_key else ""

    pairs: list[tuple[str, str, Any]] = [
        (attribute, field_name, payload.get(field_name))
        for field_name, attribute in sorted(FIELD_ATTRIBUTES.get(source_role, {}).items())
    ]

    name_field, name_value = _name_field(source_role, payload)
    if name_value:
        pairs.append(("legal_name", name_field, name_value))
        if source_role == "credentials":
            pairs.append(("name_on_credential", name_field, name_value))
    if number_key:
        pairs.append(("credential_number", "license_number", payload.get("license_number")))

    claims: list[Claim] = []
    for attribute, field_name, value in pairs:
        text = "" if value is None else str(value).strip()
        if not text:
            continue
        if attribute in CREDENTIAL_ATTRIBUTES:
            if not credential_id:
                continue
            entity_type, entity_id = ENTITY_CREDENTIAL, credential_id
        else:
            if not person_id:
                continue
            entity_type, entity_id = ENTITY_PERSON, person_id
        claims.append(
            Claim(
                entity_type=entity_type,
                entity_id=entity_id,
                attribute=attribute,
                value_norm=text,
                value_raw=_raw_value(raw, field_name),
                source_type=source_type,
                source_role=source_role,
                file_id=file_id,
                locator={"row": row_index, "column": field_name},
                observed_on=observed_on,
                quality=qualities.get(field_name, "ok"),
            )
        )
    return claims


def _name_field(source_role: str, payload: Mapping[str, Any]) -> tuple[str, str]:
    """Which column held the person's name, and what it said."""
    for field_name in ("employee_name", "name_on_license", "name_on_credential", "driver_name"):
        value = str(payload.get(field_name) or "").strip()
        if value:
            return (field_name, value)
    given = str(payload.get("first_name") or "").strip()
    family = str(payload.get("last_name") or "").strip()
    if given or family:
        return ("last_name", f"{given} {family}".strip())
    return ("", "")


def _observed_on(source_role: str, payload: Mapping[str, Any]) -> date | None:
    """The date the source vouches for its values.

    Not the date we read the file. A credential verified last week is better evidence
    than the same field copied into HR two years ago, and that is only decidable if
    each claim carries the date its source stands behind.
    """
    if source_role == "credentials":
        return _as_date(payload.get("last_verified"))
    if source_role == "payroll":
        return _as_date(payload.get("period_end"))
    return None


def claims_from_segments(segments: Sequence[Mapping[str, Any]]) -> list[Claim]:
    """What the rota says about where somebody was and in what role."""
    claims: list[Claim] = []
    seen: set[tuple[str, str, str]] = set()
    for segment in segments:
        person_id = str(segment.get("person_id") or "")
        if not person_id:
            continue
        work_date = segment.get("work_date")
        locator = {
            "page": segment.get("page"),
            "row": segment.get("row_index"),
            "column": segment.get("column_header"),
        }
        for attribute, value in (
            ("worked_facility", segment.get("facility_code")),
            ("worked_role", segment.get("role_code")),
            ("legal_name", segment.get("person_ref")),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            # One claim per distinct value per person: a rota repeats the same fact
            # once per cell, and 46 identical claims would drown the evidence list.
            marker = (person_id, attribute, text)
            if marker in seen:
                continue
            seen.add(marker)
            claims.append(
                Claim(
                    entity_type=ENTITY_PERSON,
                    entity_id=person_id,
                    attribute=attribute,
                    value_norm=text,
                    value_raw=str(segment.get("raw_text") or ""),
                    source_type=str(segment.get("source_type") or "schedule"),
                    source_role="schedule",
                    file_id=str(segment.get("file_id") or ""),
                    locator=locator,
                    observed_on=_as_date(work_date),
                )
            )
    return claims
