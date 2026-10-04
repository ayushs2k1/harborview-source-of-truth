"""Deciding who is who.

The order matters and is the spec's: human decisions first, then the deterministic
credential anchor, then weighted scoring for everything left. Each step is more
willing to be wrong than the one before it, so each only sees what the previous one
could not settle.

Nothing is thrown away. A record that matches nobody becomes a provisional person
rather than disappearing, because a nurse who is paid but not in the roster is the
single most interesting thing this system can find, and she only stays visible if she
has somewhere to be.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sot.canon import canonical_json
from sot.decisions.store import DecisionSet
from sot.ids import provisional_person_id, stable_id
from sot.normalize.names import PersonName, parse_name
from sot.resolve.candidates import PersonIndex
from sot.resolve.scoring import (
    BAND_AUTO,
    BAND_NONE,
    BAND_REVIEW,
    DECIDED_ANCHOR,
    DECIDED_AUTO,
    DECIDED_HUMAN,
    Candidate,
    MatchConfig,
    Mention,
    PersonRecord,
    is_ambiguous,
    rank_candidates,
    score_pair,
)
from sot.rules.model import Entity, Finding

#: Which rule a source's unmatched records raise.
UNMATCHED_CODES = {
    "payroll": "UNMATCHED_PAYROLL",
    "schedule": "UNMATCHED_SCHEDULE",
    "credentials": "UNMATCHED_LICENSE",
}

#: Which rule a repeated record raises, by the scope it repeated within.
DUPLICATE_CODES = {
    "payroll": "DUPLICATE_PAY_PERIOD",
    "schedule": "DUPLICATE_SCHEDULE_ROW",
}

#: Below this Jaro-Winkler similarity, two names linked by credential number are
#: different enough to be worth a human look.
NAME_MISMATCH_THRESHOLD = 0.80


@dataclass
class Link:
    """One source record attached to one person, with the reasoning kept."""

    person_id: str
    source_type: str
    record_id: str
    fingerprint: str = ""
    score: float | None = None
    band: str = BAND_AUTO
    decided_by: str = DECIDED_AUTO
    explanation: dict[str, Any] = field(default_factory=dict)

    @property
    def link_id(self) -> str:
        return stable_id("LK", {"person": self.person_id, "record": self.record_id})

    def as_row(self, run_id: str) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "link_id": self.link_id,
            "person_id": self.person_id,
            "source_type": self.source_type,
            "record_id": self.record_id,
            "fingerprint": self.fingerprint,
            "score": self.score,
            "band": self.band,
            "decided_by": self.decided_by,
            "explanation_json": canonical_json(self.explanation),
        }


@dataclass
class Resolution:
    """Everything identity resolution worked out."""

    persons: list[PersonRecord] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def person_for(self, record_id: str) -> str | None:
        return next((link.person_id for link in self.links if link.record_id == record_id), None)

    def codes(self) -> list[str]:
        return sorted({finding.code for finding in self.findings})


def _entity(person: PersonRecord) -> Entity:
    return Entity("person", person.person_id, person.display_name or person.person_id)


def _name_similarity(left: PersonName | None, right: PersonName | None) -> float:
    from rapidfuzz.distance import JaroWinkler

    if left is None or right is None:
        return 1.0
    return JaroWinkler.normalized_similarity(left.key, right.key)


# ---------------------------------------------------------------------------
# Checks within the roster itself
# ---------------------------------------------------------------------------


def check_roster(persons: Sequence[PersonRecord]) -> list[Finding]:
    """Problems visible in the roster before any matching happens.

    These are the ones that make every downstream figure unreliable, so they are
    looked for first and reported whatever else happens.
    """
    findings: list[Finding] = []

    by_employee_id: dict[str, list[PersonRecord]] = {}
    by_name: dict[str, list[PersonRecord]] = {}
    by_phone: dict[str, list[PersonRecord]] = {}
    by_credential: dict[str, list[PersonRecord]] = {}

    for person in sorted(persons, key=lambda item: item.person_id):
        if person.employee_id:
            by_employee_id.setdefault(person.employee_id.upper(), []).append(person)
        if person.name:
            by_name.setdefault(person.name.key, []).append(person)
        if person.phone_key:
            by_phone.setdefault(person.phone_key, []).append(person)
        if person.credential_key:
            by_credential.setdefault(person.credential_key.upper(), []).append(person)

    for employee_id, group in sorted(by_employee_id.items()):
        names = {person.name.key for person in group if person.name}
        if len(names) > 1:
            first, second = group[0], group[1]
            findings.append(
                Finding(
                    "EMPLOYEE_ID_COLLISION",
                    {
                        "employee_id": employee_id,
                        "first_name": first.display_name,
                        "second_name": second.display_name,
                    },
                    entities=tuple(_entity(person) for person in group[:4]),
                    key_parts=(employee_id,),
                )
            )

    for key, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        shared: list[str] = []
        if len({person.phone_key for person in group if person.phone_key}) == 1 and any(
            person.phone_key for person in group
        ):
            shared.append("a phone number")
        if len({person.credential_key for person in group if person.credential_key}) == 1 and any(
            person.credential_key for person in group
        ):
            shared.append("a credential number")
        if not shared:
            continue
        findings.append(
            Finding(
                "DUPLICATE_PERSON_HR",
                {
                    "display_name": group[0].display_name,
                    "first_id": group[0].employee_id or group[0].person_id,
                    "second_id": group[1].employee_id or group[1].person_id,
                    "shared": " and ".join(shared),
                },
                entities=tuple(_entity(person) for person in group[:4]),
                key_parts=(key,),
            )
        )

    for phone, group in sorted(by_phone.items()):
        names = {person.name.key for person in group if person.name}
        if len(group) > 1 and len(names) > 1:
            findings.append(
                Finding(
                    "SHARED_PHONE",
                    {
                        "first_name": group[0].display_name,
                        "second_name": group[1].display_name,
                        "phone": phone,
                    },
                    entities=tuple(_entity(person) for person in group[:4]),
                    key_parts=(phone,),
                )
            )

    for number, group in sorted(by_credential.items()):
        names = {person.name.key for person in group if person.name}
        if len(group) > 1 and len(names) > 1:
            findings.append(
                Finding(
                    "LICENSE_NUMBER_SHARED",
                    {
                        "number": number,
                        "first_name": group[0].display_name,
                        "second_name": group[1].display_name,
                    },
                    entities=tuple(_entity(person) for person in group[:4]),
                    key_parts=(number,),
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve(
    persons: Sequence[PersonRecord],
    mentions: Sequence[Mention],
    config: MatchConfig,
    *,
    decisions: DecisionSet | None = None,
    roster_supplied: bool = True,
) -> Resolution:
    """Attach every source record to a person, inventing one where none exists.

    ``roster_supplied`` says whether there was anything to match against. When there
    was not, records still become provisional people so the data stays usable, but
    they are not each reported as unknown - a roster nobody uploaded is one problem,
    not one problem per row, and the missing source is reported on its own.
    """
    decisions = decisions or DecisionSet()
    result = Resolution(persons=list(persons))
    result.findings.extend(check_roster(persons))

    index = PersonIndex(persons, config)
    ordered = sorted(mentions, key=lambda mention: (mention.source_role, mention.record_id))

    unmatched: list[Mention] = []
    # Mentions linked automatically, grouped by the scope they must be unique within.
    claims: dict[tuple[Any, ...], list[tuple[Mention, Candidate]]] = {}

    for mention in ordered:
        decided = decisions.accepted_person(mention.fingerprint)
        if decided and decided in index.by_id:
            person = index.by_id[decided]
            total, features = score_pair(mention, person, config)
            result.links.append(
                Link(
                    person_id=decided,
                    source_type=mention.source_type,
                    record_id=mention.record_id,
                    fingerprint=mention.fingerprint,
                    score=total,
                    band=BAND_AUTO,
                    decided_by=DECIDED_HUMAN,
                    explanation=Candidate(decided, total, features, BAND_AUTO).explanation(
                        "confirmed by a person"
                    ),
                )
            )
            continue

        anchored = _anchor(mention, index)
        if anchored is not None:
            person, candidate = anchored
            result.links.append(
                Link(
                    person_id=person.person_id,
                    source_type=mention.source_type,
                    record_id=mention.record_id,
                    fingerprint=mention.fingerprint,
                    score=candidate.score,
                    band=BAND_AUTO,
                    decided_by=DECIDED_ANCHOR,
                    explanation=candidate.explanation("matched on the credential number"),
                )
            )
            similarity = _name_similarity(mention.name, person.name)
            if similarity < NAME_MISMATCH_THRESHOLD:
                result.findings.append(
                    Finding(
                        "NAME_MISMATCH_LICENSE",
                        {
                            "number": mention.credential_key or "",
                            "display_name": person.display_name,
                            "name_on_credential": mention.display,
                        },
                        entities=(_entity(person),),
                        key_parts=(person.person_id, mention.credential_key or ""),
                    )
                )
            continue

        pool = [
            person
            for person in index.candidates(mention)
            if not decisions.is_rejected(mention.fingerprint, person.person_id)
        ]
        ranked = rank_candidates(mention, pool, config)
        if not ranked or ranked[0].band == BAND_NONE:
            unmatched.append(mention)
            continue

        best = ranked[0]
        if is_ambiguous(ranked, config):
            second = ranked[1]
            result.findings.append(
                Finding(
                    "MATCH_AMBIGUOUS",
                    {
                        "source_label": mention.source_type,
                        "record_label": mention.label or mention.display or mention.record_id,
                        "first_name": index.by_id[best.person_id].display_name,
                        "first_score": best.score,
                        "second_name": index.by_id[second.person_id].display_name,
                        "second_score": second.score,
                    },
                    entities=(
                        _entity(index.by_id[best.person_id]),
                        _entity(index.by_id[second.person_id]),
                    ),
                    row_index=mention.row_index,
                    page=mention.page,
                    key_parts=(mention.record_id,),
                )
            )
            unmatched.append(mention)
            continue

        if best.band == BAND_REVIEW:
            result.findings.append(
                Finding(
                    "MATCH_REVIEW",
                    {
                        "source_label": mention.source_type,
                        "record_label": mention.label or mention.display or mention.record_id,
                        "display_name": index.by_id[best.person_id].display_name,
                        "score": best.score,
                        "low": config.review,
                        "high": config.auto,
                    },
                    entities=(_entity(index.by_id[best.person_id]),),
                    row_index=mention.row_index,
                    page=mention.page,
                    key_parts=(mention.record_id,),
                )
            )
            unmatched.append(mention)
            continue

        claims.setdefault((mention.source_role, best.person_id, *mention.scope), []).append(
            (mention, best)
        )

    _settle_claims(result, claims, index, config, ordered)
    _add_provisional(result, unmatched, report=roster_supplied)
    return result


def _anchor(mention: Mention, index: PersonIndex) -> tuple[PersonRecord, Candidate] | None:
    """Link on an exact credential number, which is issued to exactly one person."""
    if not mention.credential_key:
        return None
    holders = index.by_credential(mention.credential_key)
    if len(holders) != 1:
        # Nobody, or two people claiming it - which is its own finding, raised by the
        # roster check. Either way the number cannot settle this on its own.
        return None
    person = holders[0]
    total, features = score_pair(mention, person, index.config)
    return (person, Candidate(person.person_id, total, features, BAND_AUTO))


def _settle_claims(
    result: Resolution,
    claims: dict[tuple[Any, ...], list[tuple[Mention, Candidate]]],
    index: PersonIndex,
    config: MatchConfig,
    ordered: Sequence[Mention],
) -> None:
    """Turn claims into links, resolving two records that claim the same slot.

    A person gets one payroll row per period, role and site, and appears once on a
    rota page. Two records claiming the same slot is either a look-alike that should
    have gone to somebody else, or a genuine duplicate. The first is reassigned if
    there is another candidate good enough; the second stays linked and is flagged,
    because a duplicated payment is the finding, not an inconvenience.

    The slot is namespaced by source. Being paid for a week and being on that week's
    rota are not two claims on one slot - they are the two halves of the match - and
    a scope that did not separate them would report every properly matched person as
    a duplicate of themselves.
    """
    for scope in sorted(claims, key=lambda item: tuple(str(part) for part in item)):
        entries = sorted(claims[scope], key=lambda item: (-item[1].score, item[0].record_id))
        winner_mention, winner_candidate = entries[0]
        result.links.append(_link_from(winner_mention, winner_candidate, index))

        for mention, candidate in entries[1:]:
            alternative = _next_auto_candidate(mention, index, config, exclude=candidate.person_id)
            if alternative is not None:
                result.links.append(_link_from(mention, alternative, index))
                continue

            result.links.append(_link_from(mention, candidate, index))
            code = DUPLICATE_CODES.get(mention.source_role)
            if code is None:
                continue
            person = index.by_id[candidate.person_id]
            result.findings.append(
                Finding(
                    code,
                    {
                        "display_name": person.display_name,
                        "facility": mention.facility_code or "",
                        "role": mention.role_code or "",
                        "count": len(entries),
                        "rows": ", ".join(
                            sorted(item.label or item.record_id for item, _ in entries)
                        ),
                        "period_start": str(mention.extra.get("period_start", "")),
                        "period_end": str(mention.extra.get("period_end", "")),
                        "total_hours": sum(
                            float(item.extra.get("hours") or 0) for item, _ in entries
                        ),
                    },
                    entities=(_entity(person),),
                    row_index=mention.row_index,
                    page=mention.page,
                    key_parts=(person.person_id, *(str(part) for part in scope)),
                )
            )


def _next_auto_candidate(
    mention: Mention, index: PersonIndex, config: MatchConfig, *, exclude: str
) -> Candidate | None:
    """The best alternative person for a mention, if one is good enough on its own."""
    pool = [person for person in index.candidates(mention) if person.person_id != exclude]
    ranked = rank_candidates(mention, pool, config)
    if ranked and ranked[0].band == BAND_AUTO and not is_ambiguous(ranked, config):
        return ranked[0]
    return None


def _link_from(mention: Mention, candidate: Candidate, index: PersonIndex) -> Link:
    person = index.by_id[candidate.person_id]
    return Link(
        person_id=candidate.person_id,
        source_type=mention.source_type,
        record_id=mention.record_id,
        fingerprint=mention.fingerprint,
        score=candidate.score,
        band=candidate.band,
        decided_by=DECIDED_AUTO,
        explanation=candidate.explanation(f"matched to {person.display_name}"),
    )


def _add_provisional(
    result: Resolution, unmatched: Iterable[Mention], *, report: bool = True
) -> None:
    """Give every unmatched record somewhere to live, and say that it has one.

    Grouped by name, role and site, so the same unknown person appearing in payroll
    and on the rota becomes one provisional person rather than two.
    """
    groups: dict[tuple[str, str, str], list[Mention]] = {}
    for mention in unmatched:
        key = (
            mention.name.key if mention.name else (mention.display or mention.record_id),
            mention.role_code or "",
            mention.facility_code or "",
        )
        groups.setdefault(key, []).append(mention)

    for key, members in sorted(groups.items()):
        name_key, role_code, facility_code = key
        person_id = provisional_person_id(
            [{"name_key": name_key, "role_code": role_code, "facility_code": facility_code}]
        )
        display = members[0].display or name_key
        name = members[0].name or parse_name(display).value
        person = PersonRecord(
            person_id=person_id,
            display_name=display,
            name=name,
            role_code=role_code or None,
            facility_code=facility_code or None,
            status="provisional",
        )
        result.persons.append(person)

        for mention in members:
            result.links.append(
                Link(
                    person_id=person_id,
                    source_type=mention.source_type,
                    record_id=mention.record_id,
                    fingerprint=mention.fingerprint,
                    score=None,
                    band=BAND_NONE,
                    decided_by=DECIDED_AUTO,
                    explanation={
                        "total": None,
                        "band": BAND_NONE,
                        "label": "no match in the roster; recorded as a provisional person",
                        "features": [],
                    },
                )
            )

        if not report:
            continue

        by_role: dict[str, list[Mention]] = {}
        for mention in members:
            by_role.setdefault(mention.source_role, []).append(mention)

        for source_role, group in sorted(by_role.items()):
            code = UNMATCHED_CODES.get(source_role)
            if code is None:
                continue
            first = group[0]
            result.findings.append(
                Finding(
                    code,
                    {
                        "name": display,
                        "display_name": display,
                        "record_label": first.label or first.display or first.record_id,
                        "facility": facility_code or "an unrecorded site",
                        "role": role_code or "",
                        "hours": first.extra.get("hours", ""),
                        "period_start": str(first.extra.get("period_start", "")),
                        "period_end": str(first.extra.get("period_end", "")),
                        "shift_count": sum(
                            int(item.extra.get("shift_count") or 0) for item in group
                        ),
                        "number": first.credential_key or "",
                        "credential_type": first.extra.get("credential_type", ""),
                        "role_requires_credential": bool(
                            first.extra.get("role_requires_credential")
                        ),
                        "credential_note": first.extra.get("credential_note", ""),
                    },
                    entities=(Entity("person", person_id, display),),
                    row_index=first.row_index,
                    page=first.page,
                    key_parts=(person_id, source_role),
                )
            )


def check_credentials_in_service(
    persons: Sequence[PersonRecord], service_keys: set[str], *, worked_roles: set[str] | None = None
) -> list[Finding]:
    """Roster credentials the verification service has never heard of.

    Only meaningful when a credential source was supplied at all - otherwise every
    person would be flagged for the absence of a file nobody sent.
    """
    if not service_keys:
        return []
    worked_roles = worked_roles or set()
    findings: list[Finding] = []
    for person in sorted(persons, key=lambda item: item.person_id):
        key = (person.credential_key or "").upper()
        if not key or key in service_keys:
            continue
        worked = person.person_id in worked_roles
        findings.append(
            Finding(
                "LICENSE_NOT_IN_SERVICE",
                {
                    "number": person.credential_key,
                    "display_name": person.display_name,
                    "worked_licensed_role": worked,
                    "work_note": (
                        " They worked in a role requiring it during the period covered."
                        if worked
                        else ""
                    ),
                },
                entities=(_entity(person),),
                key_parts=(person.person_id, key),
            )
        )
    return findings
