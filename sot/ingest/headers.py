"""Matching a file's column headings to a contract's canonical fields.

This is the join between what a system exported and what the engine understands, and
it is the single place most likely to decide whether an unfamiliar file works at all.
Three strategies, tried in order:

1. **A human said so.** A stored ``HEADER_MAP`` decision wins outright.
2. **Exact synonym.** The heading, folded to letters and digits, is one of the
   spellings the contract lists.
3. **Similar enough.** Jaro-Winkler above the pack's threshold, which catches
   ``Hours Pd``, ``period_strt``, and the rest of what real exports contain.

Anything still unmatched is kept as evidence rather than dropped, because a column we
do not understand is not the same as a column that does not matter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from rapidfuzz.distance import JaroWinkler

from sot.ingest.contracts import Column, Contract, header_key

#: Matching strategies, most authoritative first.
METHOD_LEARNED = "learned"
METHOD_EXACT = "exact"
METHOD_FUZZY = "fuzzy"

_METHOD_RANK = {METHOD_LEARNED: 0, METHOD_EXACT: 1, METHOD_FUZZY: 2}


@dataclass(frozen=True)
class HeaderMatch:
    """One column heading and what it was taken to mean."""

    index: int
    raw: str
    column: Column | None = None
    method: str = ""
    score: float = 0.0

    @property
    def canonical(self) -> str | None:
        return self.column.name if self.column else None

    def beats(self, other: HeaderMatch) -> bool:
        """True when this match should win a contest for the same canonical field."""
        mine = (_METHOD_RANK.get(self.method, 9), -self.score, self.index)
        theirs = (_METHOD_RANK.get(other.method, 9), -other.score, other.index)
        return mine < theirs


@dataclass
class HeaderMapping:
    """The result of matching one header row against one contract."""

    contract: Contract
    matches: list[HeaderMatch] = field(default_factory=list)
    by_canonical: dict[str, HeaderMatch] = field(default_factory=dict)
    unmapped: list[HeaderMatch] = field(default_factory=list)
    #: Canonical field -> the losing headings that also claimed it.
    ambiguous: dict[str, list[HeaderMatch]] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def index_to_canonical(self) -> dict[int, str]:
        """Column position to canonical field, for reading data rows."""
        return {match.index: name for name, match in self.by_canonical.items()}

    def indexes_of_type(self, *types: str) -> frozenset[int]:
        """Positions whose contract column has one of these types."""
        return frozenset(
            match.index
            for match in self.by_canonical.values()
            if match.column and match.column.type in types
        )


def _fuzzy_best(key: str, contract: Contract, threshold: float) -> tuple[Column | None, float]:
    """Closest column by Jaro-Winkler over the folded heading."""
    best: Column | None = None
    best_score = 0.0
    for column in contract.columns:
        for candidate in column.keys:
            score = JaroWinkler.normalized_similarity(key, candidate)
            if score > best_score:
                best, best_score = column, score
    return (best, best_score) if best_score >= threshold else (None, best_score)


def map_headers(
    header_row: list[str],
    contract: Contract,
    *,
    similarity: float = 0.90,
    learned: Mapping[str, str] | None = None,
) -> HeaderMapping:
    """Match one header row against one contract.

    ``learned`` maps a folded heading to a canonical field name, from stored decisions.
    It is applied before the automatic strategies rather than after them: a human who
    has already answered this question should not be overruled by a fuzzy match that
    happens to score well.
    """
    learned = learned or {}
    mapping = HeaderMapping(contract=contract)
    by_name = contract.by_name

    candidates: list[HeaderMatch] = []
    for index, raw in enumerate(header_row):
        text = str(raw).strip()
        if not text:
            continue
        key = header_key(text)
        if not key:
            continue

        learned_name = learned.get(key)
        if learned_name and learned_name in by_name:
            candidates.append(HeaderMatch(index, text, by_name[learned_name], METHOD_LEARNED, 1.0))
            continue

        exact = contract.column_for_key(key)
        if exact is not None:
            candidates.append(HeaderMatch(index, text, exact, METHOD_EXACT, 1.0))
            continue

        column, score = _fuzzy_best(key, contract, similarity)
        if column is not None:
            candidates.append(HeaderMatch(index, text, column, METHOD_FUZZY, score))
        else:
            candidates.append(HeaderMatch(index, text, None, "", score))

    for match in candidates:
        mapping.matches.append(match)
        name = match.canonical
        if name is None:
            mapping.unmapped.append(match)
            continue
        incumbent = mapping.by_canonical.get(name)
        if incumbent is None:
            mapping.by_canonical[name] = match
        elif match.beats(incumbent):
            mapping.by_canonical[name] = match
            mapping.ambiguous.setdefault(name, []).append(incumbent)
            mapping.unmapped.append(incumbent)
        else:
            mapping.ambiguous.setdefault(name, []).append(match)
            mapping.unmapped.append(match)

    mapping.missing_required = contract.missing_required(set(mapping.by_canonical))
    mapping.score = signature_score(contract, set(mapping.by_canonical))
    return mapping


def signature_score(
    contract: Contract,
    matched: set[str],
    *,
    required_weight: float = 3.0,
    optional_weight: float = 1.0,
) -> float:
    """How much of a contract's signature a file matched, from 0 to 1.

    Required columns weigh more than optional ones for two reasons. They are what makes
    a source recognisable - a file with a pay period and paid hours is payroll whatever
    else it has. And without the weighting, adding optional synonyms to a contract would
    dilute its own signature, which would make the system worse the more we taught it.

    Extra columns in the file are not penalised. A real export has columns we have never
    heard of, and a classifier that reads that as "not payroll" is useless on real data.
    """
    total = 0.0
    hit = 0.0
    for column in contract.columns:
        weight = required_weight if column.required else optional_weight
        total += weight
        if column.name in matched:
            hit += weight
    return hit / total if total else 0.0
