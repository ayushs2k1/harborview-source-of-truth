"""Comparing two records, feature by feature.

Each feature answers one question - do the family names agree, do the given names,
the role, the site, the credential number - and returns a level and the weight that
level is worth. The weights come from the pack, so a judge who disputes one can change
it and re-run rather than argue with the source.

Every comparison records what it compared as well as what it concluded, because the
person page renders this as a waterfall and "why did you think these were the same
nurse" is the question the whole system has to be able to answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jellyfish
from rapidfuzz.distance import JaroWinkler

from sot.normalize.names import PersonName, fold, looks_like_initial
from sot.normalize.nicknames import are_variants

#: Levels, in the order they are tried. "unknown" means one side had nothing to
#: compare, which is not evidence either way and scores zero.
LEVEL_EXACT = "exact"
LEVEL_VARIANT = "variant"
LEVEL_SIMILAR = "similar"
LEVEL_PHONETIC = "phonetic"
LEVEL_INITIAL = "initial"
LEVEL_SAME = "same"
LEVEL_COMPATIBLE = "compatible"
LEVEL_DIFFERENT = "different"
LEVEL_UNKNOWN = "unknown"

#: Human wording for the waterfall, per level.
LEVEL_LABELS = {
    LEVEL_EXACT: "exactly the same",
    LEVEL_VARIANT: "a known variant",
    LEVEL_SIMILAR: "nearly the same",
    LEVEL_PHONETIC: "sounds the same",
    LEVEL_INITIAL: "the same initial",
    LEVEL_SAME: "the same",
    LEVEL_COMPATIBLE: "closely related",
    LEVEL_DIFFERENT: "different",
    LEVEL_UNKNOWN: "not comparable",
}


@dataclass(frozen=True)
class FeatureScore:
    """One feature's verdict on a pair."""

    feature: str
    level: str
    weight: float
    left: str = ""
    right: str = ""
    detail: str = ""

    @property
    def label(self) -> str:
        return LEVEL_LABELS.get(self.level, self.level)

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "level": self.level,
            "label": self.label,
            "weight": self.weight,
            "left": self.left,
            "right": self.right,
            "detail": self.detail,
        }


def _weight(weights: Mapping[str, Any], feature: str, level: str) -> float:
    table = weights.get(feature) or {}
    return float(table.get(level, 0.0))


def sounds_alike(left: str, right: str) -> bool:
    """True when two names share a phonetic code.

    Two algorithms, either of which is enough. Metaphone and NYSIIS disagree often
    and each catches spellings the other does not; for a feature worth half a strong
    match, the looser reading is the useful one.
    """
    if not left or not right:
        return False
    try:
        if jellyfish.metaphone(left) == jellyfish.metaphone(right):
            return True
        return jellyfish.nysiis(left) == jellyfish.nysiis(right)
    except Exception:
        return False


def compare_last_name(
    left: PersonName | None,
    right: PersonName | None,
    weights: Mapping[str, Any],
    *,
    similar_threshold: float = 0.94,
) -> FeatureScore:
    """The strongest single name signal, and the one with the harshest penalty."""
    a = left.family_key if left else ""
    b = right.family_key if right else ""
    shown = ((left.family if left else ""), (right.family if right else ""))
    if not a or not b:
        return FeatureScore("last_name", LEVEL_UNKNOWN, 0.0, *shown, "one side has no family name")
    if a == b:
        return FeatureScore(
            "last_name", LEVEL_EXACT, _weight(weights, "last_name", "exact"), *shown
        )

    similarity = JaroWinkler.normalized_similarity(a, b)
    if similarity >= similar_threshold:
        return FeatureScore(
            "last_name",
            LEVEL_SIMILAR,
            _weight(weights, "last_name", "similar"),
            *shown,
            f"similarity {similarity:.2f}",
        )
    if sounds_alike(a, b):
        return FeatureScore(
            "last_name", LEVEL_PHONETIC, _weight(weights, "last_name", "phonetic"), *shown
        )
    return FeatureScore(
        "last_name",
        LEVEL_DIFFERENT,
        _weight(weights, "last_name", "different"),
        *shown,
        f"similarity {similarity:.2f}",
    )


def compare_first_name(
    left: PersonName | None,
    right: PersonName | None,
    weights: Mapping[str, Any],
    *,
    similar_threshold: float = 0.90,
) -> FeatureScore:
    """Given names, where shortened forms are the norm rather than the exception."""
    a = left.given if left else ""
    b = right.given if right else ""
    key_a, key_b = fold(a), fold(b)
    if not key_a or not key_b:
        return FeatureScore("first_name", LEVEL_UNKNOWN, 0.0, a, b, "one side has no given name")
    if key_a == key_b:
        return FeatureScore(
            "first_name", LEVEL_EXACT, _weight(weights, "first_name", "exact"), a, b
        )
    if are_variants(a, b):
        return FeatureScore(
            "first_name",
            LEVEL_VARIANT,
            _weight(weights, "first_name", "variant"),
            a,
            b,
            "a known short form or spelling variant",
        )

    similarity = JaroWinkler.normalized_similarity(key_a, key_b)
    if similarity >= similar_threshold:
        return FeatureScore(
            "first_name",
            LEVEL_SIMILAR,
            _weight(weights, "first_name", "similar"),
            a,
            b,
            f"similarity {similarity:.2f}",
        )
    if (looks_like_initial(a) or looks_like_initial(b)) and key_a[0] == key_b[0]:
        return FeatureScore(
            "first_name",
            LEVEL_INITIAL,
            _weight(weights, "first_name", "initial"),
            a,
            b,
            "one side is only an initial",
        )
    return FeatureScore(
        "first_name",
        LEVEL_DIFFERENT,
        _weight(weights, "first_name", "different"),
        a,
        b,
        f"similarity {similarity:.2f}",
    )


def compare_role(
    left: str | None,
    right: str | None,
    weights: Mapping[str, Any],
    *,
    families: Mapping[str, list[str]] | None = None,
) -> FeatureScore:
    """Roles, with a modest penalty because people legitimately cover other roles."""
    a, b = (left or "").upper(), (right or "").upper()
    if not a or not b:
        return FeatureScore("role", LEVEL_UNKNOWN, 0.0, a, b, "one side has no role")
    if a == b:
        return FeatureScore("role", LEVEL_SAME, _weight(weights, "role", "same"), a, b)

    for name, members in sorted((families or {}).items()):
        upper = {str(member).upper() for member in members}
        if a in upper and b in upper:
            return FeatureScore(
                "role",
                LEVEL_COMPATIBLE,
                _weight(weights, "role", "compatible"),
                a,
                b,
                f"both are {name.replace('_', ' ')} roles",
            )
    return FeatureScore("role", LEVEL_DIFFERENT, _weight(weights, "role", "different"), a, b)


def compare_facility(
    left: str | None, right: str | None, weights: Mapping[str, Any]
) -> FeatureScore:
    """Site, worth little either way: floats between facilities are normal."""
    a, b = (left or "").upper(), (right or "").upper()
    if not a or not b:
        return FeatureScore("facility", LEVEL_UNKNOWN, 0.0, a, b, "one side has no site")
    if a == b:
        return FeatureScore("facility", LEVEL_SAME, _weight(weights, "facility", "same"), a, b)
    return FeatureScore(
        "facility",
        LEVEL_DIFFERENT,
        _weight(weights, "facility", "different"),
        a,
        b,
        "staff do float between sites",
    )


def compare_credential(
    left: str | None, right: str | None, weights: Mapping[str, Any]
) -> FeatureScore:
    """The decisive feature when both sides have one.

    A credential number is issued to one person, so agreement is worth more than every
    other feature combined and disagreement is strong evidence against. Only compared
    when both sides have one: a roster that does not record the number says nothing.
    """
    a, b = (left or "").upper(), (right or "").upper()
    if not a or not b:
        return FeatureScore(
            "credential", LEVEL_UNKNOWN, 0.0, a, b, "only one side records a credential number"
        )
    if a == b:
        return FeatureScore(
            "credential", LEVEL_EXACT, _weight(weights, "credential", "exact"), a, b
        )
    return FeatureScore(
        "credential", LEVEL_DIFFERENT, _weight(weights, "credential", "different"), a, b
    )
