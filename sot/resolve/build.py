"""Turning standardized records into people and mentions.

The roster seeds the people. Every other source produces mentions - records that are
about somebody, without saying who. This module is the only place that knows which
canonical field means what, so the matcher itself stays free of source vocabulary.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sot.ids import person_id_from_employee_id, provisional_person_id, record_fingerprint
from sot.ingest.contracts import Pack
from sot.normalize.names import PersonName, parse_name
from sot.resolve.scoring import Mention, PersonRecord

#: Canonical fields holding a person's name, in the order they are preferred.
NAME_FIELDS = ("employee_name", "name_on_license", "name_on_credential", "driver_name")


def _payload(record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(record.get("payload_json") or "{}")
    except (TypeError, ValueError):
        return {}


def name_from_payload(payload: Mapping[str, Any], field: str) -> PersonName | None:
    """Rebuild a parsed name from the parts stored beside it.

    Reconstructed rather than re-parsed: the parts are what the normalizer actually
    decided, and parsing the display form again could reach a different answer for an
    awkward name - which would mean the matcher and the stored record disagreed.
    """
    display = str(payload.get(field) or "").strip()
    if not display:
        return None
    family = str(payload.get(f"{field}__family") or "")
    if not family:
        return parse_name(display).value
    return PersonName(
        raw=display,
        given=str(payload.get(f"{field}__given") or ""),
        middle=str(payload.get(f"{field}__middle") or ""),
        family=family,
        suffix=str(payload.get(f"{field}__suffix") or ""),
    )


def _roster_name(payload: Mapping[str, Any]) -> PersonName | None:
    """A roster may split the name into columns or keep it in one."""
    combined = name_from_payload(payload, "employee_name")
    if combined is not None:
        return combined
    given = str(payload.get("first_name") or "").strip()
    middle = str(payload.get("middle_name") or "").strip()
    family = str(payload.get("last_name") or "").strip()
    if not family and not given:
        return None
    parsed = parse_name(f"{family}, {given} {middle}".strip().rstrip(","))
    return parsed.value


def build_persons(records: Iterable[Mapping[str, Any]], pack: Pack) -> list[PersonRecord]:
    """Seed the people from the roster.

    An employer-issued identifier makes a stable person id. Without one the id is
    derived from the name, role and site, which is weaker but still survives a
    re-export - row numbers never enter into it.
    """
    people: list[PersonRecord] = []
    for record in sorted(records, key=lambda item: (item["file_id"], item["row_index"])):
        payload = _payload(record)
        name = _roster_name(payload)
        employee_id = str(payload.get("employee_id") or "").strip()
        role_code = str(payload.get("job_code") or payload.get("job_title") or "").strip()
        facility = str(payload.get("facility_code") or payload.get("facility") or "").strip()

        if employee_id:
            person_id = person_id_from_employee_id(employee_id)
            status = "confirmed"
        else:
            person_id = provisional_person_id(
                [
                    {
                        "name_key": name.key if name else "",
                        "role_code": role_code,
                        "facility_code": facility,
                    }
                ]
            )
            status = "provisional"

        people.append(
            PersonRecord(
                person_id=person_id,
                display_name=(name.display if name else "") or employee_id or person_id,
                name=name,
                role_code=role_code or None,
                facility_code=facility or None,
                credential_key=str(payload.get("license_number__key") or "") or None,
                employee_id=employee_id or None,
                phone_key=str(payload.get("phone__key") or "") or None,
                status=status,
                record_id=str(record.get("record_id") or ""),
                file_id=str(record.get("file_id") or ""),
                row_index=record.get("row_index"),
            )
        )
    return people


def build_payroll_mentions(records: Iterable[Mapping[str, Any]]) -> list[Mention]:
    """One mention per payroll row.

    The scope is the pay period, role and site: a person gets one row per combination,
    and a second is a possible duplicate payment rather than a second person.
    """
    mentions: list[Mention] = []
    for record in records:
        payload = _payload(record)
        name = name_from_payload(payload, "employee_name")
        role = str(payload.get("job_code") or "").strip()
        facility = str(payload.get("facility_code") or "").strip()
        period_start = str(payload.get("period_start") or "")
        mentions.append(
            Mention(
                record_id=str(record["record_id"]),
                source_type=str(record["source_type"]),
                source_role="payroll",
                display=str(payload.get("employee_name") or ""),
                label=str(payload.get("payroll_id") or ""),
                name=name,
                role_code=role or None,
                facility_code=facility or None,
                fingerprint=record_fingerprint(
                    str(record["source_type"]), name.key if name else "", role, facility
                ),
                scope=(period_start, role, facility),
                file_id=str(record.get("file_id") or ""),
                row_index=record.get("row_index"),
                extra={
                    "hours": payload.get("hours_paid"),
                    "period_start": period_start,
                    "period_end": payload.get("period_end", ""),
                },
            )
        )
    return mentions


def build_credential_mentions(records: Iterable[Mapping[str, Any]]) -> list[Mention]:
    """One mention per credential row, carrying the number that anchors it."""
    mentions: list[Mention] = []
    for record in records:
        payload = _payload(record)
        name = name_from_payload(payload, "name_on_license") or name_from_payload(
            payload, "name_on_credential"
        )
        credential_type = str(payload.get("license_type") or "").strip()
        mentions.append(
            Mention(
                record_id=str(record["record_id"]),
                source_type=str(record["source_type"]),
                source_role="credentials",
                display=str(payload.get("name_on_license") or ""),
                label=str(payload.get("license_number") or ""),
                name=name,
                role_code=credential_type or None,
                credential_key=str(payload.get("license_number__key") or "") or None,
                fingerprint=record_fingerprint(
                    str(record["source_type"]), name.key if name else "", credential_type, ""
                ),
                scope=(),
                file_id=str(record.get("file_id") or ""),
                row_index=record.get("row_index"),
                extra={
                    "credential_type": credential_type,
                    "number": payload.get("license_number", ""),
                },
            )
        )
    return mentions


def build_schedule_mentions(
    segments: Sequence[Mapping[str, Any]], pack: Pack | None = None
) -> list[Mention]:
    """One mention per rota row, not per cell.

    A person occupies one row of a page; the cells across it are the same person's
    week. Matching per cell would ask the same question seven times and let the
    answers disagree.
    """
    requires_credential = _roles_requiring_credential(pack)
    rows: dict[tuple[str, int, int], list[Mapping[str, Any]]] = {}
    for segment in segments:
        key = (
            str(segment.get("file_id") or ""),
            int(segment.get("page") or 0),
            int(segment.get("row_index") or 0),
        )
        rows.setdefault(key, []).append(segment)

    mentions: list[Mention] = []
    parsed_names: dict[str, PersonName | None] = {}
    for key, group in sorted(rows.items()):
        file_id, page, row_index = key
        first = group[0]
        display = str(first.get("person_ref") or "")
        if display not in parsed_names:
            parsed_names[display] = parse_name(display).value
        name = parsed_names[display]
        role = str(first.get("role_code") or "")
        facility = str(first.get("facility_code") or "")
        mentions.append(
            Mention(
                record_id=f"SCHED-{file_id}-{page}-{row_index}",
                source_type=str(first.get("source_type") or "schedule"),
                source_role="schedule",
                display=display,
                label=display,
                name=name,
                role_code=role or None,
                facility_code=facility or None,
                fingerprint=record_fingerprint(
                    str(first.get("source_type") or "schedule"),
                    name.key if name else "",
                    role,
                    facility,
                ),
                scope=(file_id, page),
                file_id=file_id,
                row_index=row_index,
                page=page,
                extra={
                    "shift_count": sum(
                        1 for item in group if item.get("category") in ("WORK", "TRAINING")
                    ),
                    "segment_ids": [item["segment_id"] for item in group],
                    "role_requires_credential": role.upper() in requires_credential,
                    "credential_note": (
                        f" The {role} role requires a credential, and none is on file."
                        if role.upper() in requires_credential
                        else ""
                    ),
                },
            )
        )
    return mentions


def _roles_requiring_credential(pack: Pack | None) -> set[str]:
    """Roles the pack says cannot be worked without a credential.

    An unknown face on the rota is a staffing note for an unlicensed role and a
    compliance problem for a licensed one, so the severity turns on this.
    """
    if pack is None:
        return set()
    crosswalk = pack.crosswalk("roles")
    if crosswalk is None:
        return set()
    return {
        entry.code.upper()
        for entry in crosswalk.entries
        if str(entry.extra.get("requires_credential", "")).strip().lower() in {"true", "yes", "1"}
    }


def person_rows(run_id: str, persons: Iterable[PersonRecord]) -> list[dict[str, Any]]:
    """Flatten people for the ``persons`` table."""
    return [
        {
            "run_id": run_id,
            "person_id": person.person_id,
            "status": person.status,
            "display_name": person.display_name,
            "name_key": person.name.key if person.name else "",
            "given": person.name.given if person.name else "",
            "middle": person.name.middle if person.name else "",
            "family": person.name.family if person.name else "",
            "suffix": person.name.suffix if person.name else "",
            "employee_id": person.employee_id,
            "home_facility": person.facility_code,
            "primary_role": person.role_code,
        }
        for person in sorted(persons, key=lambda item: item.person_id)
    ]
