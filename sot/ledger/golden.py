"""Golden records: deciding which claim to show.

Survivorship is a *view* over the ledger, not a merge. Every claim stays queryable,
the winner records which rule picked it, and the count of competing values is kept so
the person page can show that two systems disagree even when one of them wins.

Conflicts come in two shapes. Two sources disagreeing about the same attribute - HR's
copy of an expiry against the verification service's - is a within-attribute conflict.
Two different attributes describing the same real-world fact disagreeing, such as
where somebody is rostered against where they are paid, is a group conflict. Both are
reported; the authority only decides what is displayed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sot.canon import dedupe
from sot.ids import stable_id
from sot.ledger.authority import Authority, deciding_rule, sort_key
from sot.ledger.claims import Claim, credential_entity_id
from sot.rules.model import Entity, Finding


@dataclass(frozen=True)
class GoldenValue:
    """The value shown for one attribute, and what it beat."""

    entity_type: str
    entity_id: str
    attribute: str
    value_norm: str
    claim_id: str
    rule: str
    source_type: str
    source_role: str
    observed_on: date | None
    candidate_count: int
    conflict_count: int
    #: The competing claims, kept so the person page can show the disagreement.
    others: tuple[Claim, ...] = ()

    @property
    def has_conflict(self) -> bool:
        return self.conflict_count > 0

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "attribute": self.attribute,
            "value_norm": self.value_norm,
            "claim_id": self.claim_id,
            "rule": self.rule,
            "source_type": self.source_type,
            "observed_on": self.observed_on,
            "candidate_count": self.candidate_count,
            "conflict_count": self.conflict_count,
        }


class Golden:
    """Golden values, indexed for lookup."""

    def __init__(self, values: Iterable[GoldenValue]) -> None:
        self.values = sorted(
            values, key=lambda item: (item.entity_type, item.entity_id, item.attribute)
        )
        self._index = {
            (item.entity_type, item.entity_id, item.attribute): item for item in self.values
        }

    def get(self, entity_type: str, entity_id: str, attribute: str) -> GoldenValue | None:
        return self._index.get((entity_type, entity_id, attribute))

    def value(self, entity_type: str, entity_id: str, attribute: str, default: str = "") -> str:
        found = self.get(entity_type, entity_id, attribute)
        return found.value_norm if found else default

    def person(self, person_id: str, attribute: str, default: str = "") -> str:
        return self.value("person", person_id, attribute, default)

    def person_date(self, person_id: str, attribute: str) -> date | None:
        return _as_date(self.person(person_id, attribute))

    def for_entity(self, entity_type: str, entity_id: str) -> list[GoldenValue]:
        return [
            item
            for item in self.values
            if item.entity_type == entity_type and item.entity_id == entity_id
        ]

    def entities(self, entity_type: str) -> list[str]:
        return dedupe([item.entity_id for item in self.values if item.entity_type == entity_type])

    def __len__(self) -> int:
        return len(self.values)


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


def survive(claims: Sequence[Claim], authority: Authority) -> Golden:
    """Pick one claim per attribute, and remember what it beat."""
    grouped: dict[tuple[str, str, str], list[Claim]] = {}
    for claim in claims:
        grouped.setdefault((claim.entity_type, claim.entity_id, claim.attribute), []).append(claim)

    values: list[GoldenValue] = []
    for key, group in sorted(grouped.items()):
        entity_type, entity_id, attribute = key
        ordered = sorted(group, key=sort_key(authority, attribute))
        winner, others = ordered[0], ordered[1:]
        distinct = {claim.value_norm for claim in ordered}
        values.append(
            GoldenValue(
                entity_type=entity_type,
                entity_id=entity_id,
                attribute=attribute,
                value_norm=winner.value_norm,
                claim_id=winner.claim_id,
                rule=deciding_rule(authority, attribute, winner, others),
                source_type=winner.source_type,
                source_role=winner.source_role,
                observed_on=winner.observed_on,
                candidate_count=len(ordered),
                conflict_count=max(len(distinct) - 1, 0),
                others=tuple(claim for claim in others if claim.value_norm != winner.value_norm),
            )
        )
    return Golden(values)


def conflict_findings(
    golden: Golden,
    authority: Authority,
    *,
    display_names: Mapping[str, str] | None = None,
    credential_holders: Mapping[str, str] | None = None,
) -> list[Finding]:
    """Report every disagreement, whichever way the authority resolved it."""
    display_names = display_names or {}
    credential_holders = credential_holders or {}
    findings: list[Finding] = []

    def name_for(entity_type: str, entity_id: str) -> tuple[str, str]:
        if entity_type == "credential":
            holder = credential_holders.get(entity_id, "")
            return (holder, display_names.get(holder, holder or entity_id))
        return (entity_id, display_names.get(entity_id, entity_id))

    for attribute, rule in sorted(authority.conflict_within.items()):
        for value in golden.values:
            if value.attribute != attribute or not value.has_conflict:
                continue
            person_id, display = name_for(value.entity_type, value.entity_id)
            loser = value.others[0]
            findings.append(
                Finding(
                    rule,
                    {
                        "display_name": display,
                        "credential_type": golden.value(
                            value.entity_type, value.entity_id, "credential_type", "credential"
                        ),
                        "service_date": value.value_norm,
                        "hr_date": loser.value_norm,
                        "values": _describe(value),
                    },
                    entities=(Entity("person", person_id, display),) if person_id else (),
                    key_parts=(value.entity_id, attribute),
                )
            )

    for group in authority.conflict_groups:
        for person_id in golden.entities("person"):
            seen: list[tuple[str, str]] = []
            for attribute in group.attributes:
                found = golden.get("person", person_id, attribute)
                if found and found.value_norm:
                    seen.append((attribute, found.value_norm))
            if len({value for _, value in seen}) < 2:
                continue
            display = display_names.get(person_id, person_id)
            findings.append(
                Finding(
                    group.rule,
                    {
                        "display_name": display,
                        "values": ", ".join(
                            f"{value} in {_source_label(attribute)}" for attribute, value in seen
                        ),
                    },
                    entities=(Entity("person", person_id, display),),
                    key_parts=(person_id, group.name),
                )
            )

    return findings


def _describe(value: GoldenValue) -> str:
    parts = [f"{value.value_norm} ({value.source_type})"]
    parts += [f"{claim.value_norm} ({claim.source_type})" for claim in value.others]
    return ", ".join(parts)


#: How an attribute reads in a conflict message.
_SOURCE_LABELS = {
    "home_facility": "the roster",
    "paid_facility": "payroll",
    "worked_facility": "the schedule",
    "job_title": "the roster",
    "paid_role": "payroll",
    "worked_role": "the schedule",
}


def _source_label(attribute: str) -> str:
    return _SOURCE_LABELS.get(attribute, attribute)


# ---------------------------------------------------------------------------
# Derived entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Credential:
    """One credential, as the golden record sees it."""

    credential_id: str
    holder_id: str
    credential_type: str = ""
    number: str = ""
    number_key: str = ""
    expires_on: date | None = None
    last_verified: date | None = None
    issued_on: date | None = None
    status: str = ""
    state: str = ""
    name_on_credential: str = ""
    source_type: str = ""
    sources: tuple[str, ...] = ()

    @property
    def in_service(self) -> bool:
        """True when the verification service, not just HR, knows about it."""
        return "credentials" in self.sources

    def valid_on(self, when: date) -> bool | None:
        """Whether the credential covers a date. ``None`` when the expiry is unknown."""
        if self.expires_on is None:
            return None
        if self.issued_on and when < self.issued_on:
            return False
        return when <= self.expires_on

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "credential_id": self.credential_id,
            "holder_type": "person",
            "holder_id": self.holder_id,
            "credential_type": self.credential_type,
            "number_norm": self.number,
            "number_raw": self.number,
            "number_prefix": self.number_key.split(":")[0] if ":" in self.number_key else "",
            "number_digits": self.number_key.split(":")[-1],
            "name_on_credential": self.name_on_credential,
            "issue_date": self.issued_on,
            "expires_on": self.expires_on,
            "last_verified": self.last_verified,
            "status": self.status,
            "state": self.state,
            "source_type": self.source_type,
        }


def build_credentials(
    golden: Golden, holders: Mapping[str, str], claims: Sequence[Claim]
) -> list[Credential]:
    """One credential per number, with the sources that spoke about it."""
    sources_by_entity: dict[str, set[str]] = {}
    for claim in claims:
        if claim.entity_type == "credential":
            sources_by_entity.setdefault(claim.entity_id, set()).add(claim.source_role)

    credentials: list[Credential] = []
    for credential_id in golden.entities("credential"):
        number = golden.value("credential", credential_id, "credential_number")
        credentials.append(
            Credential(
                credential_id=credential_id,
                holder_id=holders.get(credential_id, ""),
                credential_type=golden.value("credential", credential_id, "credential_type"),
                number=number,
                number_key=_number_key(number, credential_id, golden),
                expires_on=_as_date(
                    golden.value("credential", credential_id, "credential_expires_on")
                ),
                last_verified=_as_date(
                    golden.value("credential", credential_id, "credential_last_verified")
                ),
                issued_on=_as_date(
                    golden.value("credential", credential_id, "credential_issued_on")
                ),
                status=golden.value("credential", credential_id, "credential_status"),
                state=golden.value("credential", credential_id, "credential_state"),
                name_on_credential=golden.value("credential", credential_id, "name_on_credential"),
                source_type=(
                    golden.get("credential", credential_id, "credential_expires_on").source_type
                    if golden.get("credential", credential_id, "credential_expires_on")
                    else ""
                ),
                sources=tuple(sorted(sources_by_entity.get(credential_id, ()))),
            )
        )
    return credentials


def _number_key(number: str, credential_id: str, golden: Golden) -> str:
    credential_type = golden.value("credential", credential_id, "credential_type")
    digits = "".join(ch for ch in number if ch.isdigit())
    return f"{credential_type}:{digits}" if credential_type else digits


def credential_holders(
    records: Iterable[Mapping[str, Any]], person_by_record: Mapping[str, str]
) -> dict[str, str]:
    """Who holds each credential, from the records that mention its number."""
    holders: dict[str, str] = {}
    for record in records:
        try:
            payload = json.loads(record.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        key = str(payload.get("license_number__key") or "").strip()
        person_id = person_by_record.get(str(record.get("record_id") or ""))
        if key and person_id:
            holders.setdefault(credential_entity_id(key), person_id)
    return holders


@dataclass(frozen=True)
class PayLine:
    """One payroll row, resolved."""

    pay_line_id: str
    person_id: str
    payroll_ref: str = ""
    facility_code: str = ""
    role_code: str = ""
    period_start: date | None = None
    period_end: date | None = None
    hours_paid: float = 0.0
    hours_worked: float | None = None
    pto_hours: float | None = None
    pay_type: str = ""
    file_id: str = ""
    row_index: int | None = None

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "pay_line_id": self.pay_line_id,
            "person_id": self.person_id,
            "payroll_ref": self.payroll_ref,
            "facility_code": self.facility_code,
            "role_code": self.role_code,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "hours_paid": self.hours_paid,
            "hours_worked": self.hours_worked,
            "pto_hours": self.pto_hours,
            "pay_type": self.pay_type,
            "file_id": self.file_id,
            "row_index": self.row_index,
        }


def build_pay_lines(
    records: Iterable[Mapping[str, Any]], person_by_record: Mapping[str, str]
) -> list[PayLine]:
    """Payroll rows with their person attached."""
    lines: list[PayLine] = []
    for record in records:
        try:
            payload = json.loads(record.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        record_id = str(record.get("record_id") or "")
        lines.append(
            PayLine(
                pay_line_id=stable_id("PL", {"record": record_id}),
                person_id=person_by_record.get(record_id, ""),
                payroll_ref=str(payload.get("payroll_id") or ""),
                facility_code=str(payload.get("facility_code") or ""),
                role_code=str(payload.get("job_code") or ""),
                period_start=_as_date(payload.get("period_start")),
                period_end=_as_date(payload.get("period_end")),
                hours_paid=_as_float(payload.get("hours_paid")),
                hours_worked=_as_optional_float(payload.get("hours_worked")),
                pto_hours=_as_optional_float(payload.get("pto_hours")),
                pay_type=str(payload.get("pay_type") or ""),
                file_id=str(record.get("file_id") or ""),
                row_index=record.get("row_index"),
            )
        )
    return sorted(lines, key=lambda line: line.pay_line_id)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_optional_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
