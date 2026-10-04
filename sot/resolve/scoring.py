"""Scoring a pair of records.

Fellegi-Sunter in the plain sense: each feature contributes evidence for or against,
the evidence is summed, and the total falls into one of three bands - link it, ask a
human, or leave it alone.

Deliberately not machine learning. There is no labelled training data for this client,
the cost of a wrong auto-link is somebody being paid or rostered as the wrong person,
and a judge is entitled to ask why any particular link was made. Hand-set weights
answer that in one sentence per feature; a model would not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sot.canon import round_hours
from sot.ingest.contracts import Pack
from sot.normalize.names import PersonName
from sot.resolve.features import (
    FeatureScore,
    compare_credential,
    compare_facility,
    compare_first_name,
    compare_last_name,
    compare_role,
)

BAND_AUTO = "auto"
BAND_REVIEW = "review"
BAND_AMBIGUOUS = "ambiguous"
BAND_NONE = "none"

DECIDED_AUTO = "auto"
DECIDED_HUMAN = "human"
DECIDED_ANCHOR = "anchor"

#: Fallback weights, used only when a pack does not configure its own.
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "last_name": {"exact": 6.0, "similar": 4.0, "phonetic": 3.0, "different": -6.0},
    "first_name": {"exact": 4.5, "variant": 3.5, "similar": 2.5, "initial": 1.0, "different": -4.5},
    "role": {"same": 1.5, "compatible": 0.5, "different": -2.0},
    "facility": {"same": 1.0, "different": -1.0},
    "credential": {"exact": 12.0, "different": -6.0},
}


@dataclass(frozen=True)
class MatchConfig:
    """Everything the matcher reads from the pack."""

    weights: Mapping[str, Mapping[str, float]] = field(default_factory=lambda: DEFAULT_WEIGHTS)
    last_name_similar: float = 0.94
    first_name_similar: float = 0.90
    auto: float = 8.0
    review: float = 3.0
    ambiguous_margin: float = 2.0
    max_persons_without_blocking: int = 2000
    role_families: Mapping[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_pack(cls, pack: Pack) -> MatchConfig:
        matching = pack.setting("matching", {}) or {}
        thresholds = matching.get("thresholds", {}) or {}
        bands = matching.get("bands", {}) or {}
        return cls(
            weights=matching.get("weights") or DEFAULT_WEIGHTS,
            last_name_similar=float(thresholds.get("last_name_similar", 0.94)),
            first_name_similar=float(thresholds.get("first_name_similar", 0.90)),
            auto=float(bands.get("auto", 8.0)),
            review=float(bands.get("review", 3.0)),
            ambiguous_margin=float(matching.get("ambiguous_margin", 2.0)),
            max_persons_without_blocking=int(matching.get("max_persons_without_blocking", 2000)),
            role_families=pack.setting("role_families", {}) or {},
        )

    def band_for(self, score: float) -> str:
        if score >= self.auto:
            return BAND_AUTO
        if score >= self.review:
            return BAND_REVIEW
        return BAND_NONE


@dataclass(frozen=True)
class PersonRecord:
    """Somebody a source record could be about."""

    person_id: str
    display_name: str = ""
    name: PersonName | None = None
    role_code: str | None = None
    facility_code: str | None = None
    credential_key: str | None = None
    employee_id: str | None = None
    phone_key: str | None = None
    status: str = "confirmed"
    record_id: str = ""
    file_id: str = ""
    row_index: int | None = None


@dataclass(frozen=True)
class Mention:
    """A source record that needs attaching to a person."""

    record_id: str
    source_type: str
    source_role: str
    #: The person, as this record writes them. Becomes a provisional person's name.
    display: str = ""
    #: The record's own identifier, for messages that need to point at the row.
    label: str = ""
    name: PersonName | None = None
    role_code: str | None = None
    facility_code: str | None = None
    credential_key: str | None = None
    fingerprint: str = ""
    #: Scope within which this mention must be unique, e.g. one pay period and site.
    scope: tuple[Any, ...] = ()
    file_id: str = ""
    row_index: int | None = None
    page: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    """One person, scored against one mention."""

    person_id: str
    score: float
    features: tuple[FeatureScore, ...]
    band: str

    def explanation(self, total_label: str = "") -> dict[str, Any]:
        """The waterfall the person page renders."""
        return {
            "total": self.score,
            "band": self.band,
            "label": total_label,
            "features": [feature.as_dict() for feature in self.features],
        }


def score_pair(
    mention: Mention, person: PersonRecord, config: MatchConfig
) -> tuple[float, tuple[FeatureScore, ...]]:
    """Score one pair, returning the total and every feature that contributed."""
    features = (
        compare_last_name(
            mention.name,
            person.name,
            config.weights,
            similar_threshold=config.last_name_similar,
        ),
        compare_first_name(
            mention.name,
            person.name,
            config.weights,
            similar_threshold=config.first_name_similar,
        ),
        compare_role(
            mention.role_code, person.role_code, config.weights, families=config.role_families
        ),
        compare_facility(mention.facility_code, person.facility_code, config.weights),
        compare_credential(mention.credential_key, person.credential_key, config.weights),
    )
    total = round_hours(sum(feature.weight for feature in features)) or 0.0
    return (total, features)


def rank_candidates(
    mention: Mention, persons: Sequence[PersonRecord], config: MatchConfig
) -> list[Candidate]:
    """Score a mention against every candidate, best first.

    Ties break on person id so that a reshuffled roster cannot change which of two
    equally good candidates wins.
    """
    scored: list[Candidate] = []
    for person in persons:
        total, features = score_pair(mention, person, config)
        scored.append(Candidate(person.person_id, total, features, config.band_for(total)))
    scored.sort(key=lambda candidate: (-candidate.score, candidate.person_id))
    return scored


def is_ambiguous(candidates: Sequence[Candidate], config: MatchConfig) -> bool:
    """True when the best two are too close to choose between.

    Checked independently of the total: two candidates scoring 11 and 10 are both
    excellent matches, and picking the higher one is a coin toss with somebody's
    payroll on it.
    """
    if len(candidates) < 2:
        return False
    best, second = candidates[0], candidates[1]
    if best.score < config.review:
        return False
    return (best.score - second.score) < config.ambiguous_margin
