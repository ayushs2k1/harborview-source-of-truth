"""Choosing which people are worth scoring against.

With ten people, score against all ten. With ten thousand, scoring every pair is a
hundred million comparisons, so candidates are narrowed first by three cheap keys -
family-name prefix, phonetic code, and site plus role - and the union is scored.

The keys are chosen so that a true match survives at least one of them: a misspelled
surname keeps its sound, a renamed one keeps its site and role, and a shortened given
name does not matter because the keys do not use it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import jellyfish

from sot.resolve.scoring import MatchConfig, Mention, PersonRecord

#: How many leading characters of a family name form a blocking key.
PREFIX_LENGTH = 3


def _prefix_key(family_key: str) -> str:
    return family_key[:PREFIX_LENGTH]


def _phonetic_key(family: str) -> str:
    if not family:
        return ""
    try:
        return jellyfish.metaphone(family)
    except Exception:
        return ""


def _site_role_key(facility: str | None, role: str | None) -> str:
    return f"{(facility or '').upper()}|{(role or '').upper()}"


class PersonIndex:
    """People to match against, with blocking keys when the roster is large."""

    def __init__(self, persons: Iterable[PersonRecord], config: MatchConfig) -> None:
        self.persons: list[PersonRecord] = sorted(persons, key=lambda person: person.person_id)
        self.config = config
        self.by_id = {person.person_id: person for person in self.persons}
        self._blocked = len(self.persons) > config.max_persons_without_blocking
        self._by_prefix: dict[str, list[PersonRecord]] = {}
        self._by_sound: dict[str, list[PersonRecord]] = {}
        self._by_site_role: dict[str, list[PersonRecord]] = {}
        self._by_credential: dict[str, list[PersonRecord]] = {}

        for person in self.persons:
            if person.credential_key:
                self._by_credential.setdefault(person.credential_key.upper(), []).append(person)
            if not self._blocked:
                continue
            family = person.name.family_key if person.name else ""
            if family:
                self._by_prefix.setdefault(_prefix_key(family), []).append(person)
                sound = _phonetic_key(family)
                if sound:
                    self._by_sound.setdefault(sound, []).append(person)
            self._by_site_role.setdefault(
                _site_role_key(person.facility_code, person.role_code), []
            ).append(person)

    @property
    def blocking(self) -> bool:
        """True when the roster is large enough to need narrowing."""
        return self._blocked

    def by_credential(self, key: str | None) -> list[PersonRecord]:
        """Everyone holding this credential number. Used by the deterministic anchor."""
        if not key:
            return []
        return list(self._by_credential.get(key.upper(), ()))

    def candidates(self, mention: Mention) -> Sequence[PersonRecord]:
        """People worth scoring this mention against."""
        if not self._blocked:
            return self.persons

        found: dict[str, PersonRecord] = {}
        for person in self.by_credential(mention.credential_key):
            found[person.person_id] = person

        family = mention.name.family_key if mention.name else ""
        if family:
            for person in self._by_prefix.get(_prefix_key(family), ()):
                found[person.person_id] = person
            sound = _phonetic_key(family)
            for person in self._by_sound.get(sound, ()):
                found[person.person_id] = person

        key = _site_role_key(mention.facility_code, mention.role_code)
        for person in self._by_site_role.get(key, ()):
            found[person.person_id] = person

        return sorted(found.values(), key=lambda person: person.person_id)
