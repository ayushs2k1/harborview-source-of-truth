"""Given-name variants.

A shortened given name on the rota and the full one in HR are the same person, and
resolving that automatically is the difference between a system that links records and
one that asks a human about every nurse.

The table is a list of equivalence classes, and membership is transitive through them.
Classes overlap on purpose - a short form like Chris belongs to more than one full name
- which makes the relation deliberately loose. It is used as *evidence* in scoring
rather than as proof, and the scoring weights say so.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from sot.normalize.names import fold


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, frozenset[str]]:
    """Folded name to the set of folded names it is equivalent to."""
    groups: list[set[str]] = []
    source = Path(path)
    if not source.is_file():
        return {}
    with open(source, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            names = [row.get("canonical", ""), *(row.get("aliases") or "").split("|")]
            folded = {fold(name) for name in names if name and fold(name)}
            if len(folded) > 1:
                groups.append(folded)

    table: dict[str, set[str]] = {}
    for group in groups:
        for name in group:
            table.setdefault(name, set()).update(group)
    return {name: frozenset(members) for name, members in table.items()}


def _table() -> dict[str, frozenset[str]]:
    from sot.config import settings

    return _load(str(settings().packs_dir / "core" / "nicknames.csv"))


def variants_of(name: str) -> frozenset[str]:
    """Every folded name equivalent to this one, including itself."""
    key = fold(name)
    if not key:
        return frozenset()
    return _table().get(key, frozenset({key})) | {key}


def are_variants(first: str, second: str) -> bool:
    """True when two given names are known forms of each other.

    Not symmetric by accident - the table is built symmetrically on load, so
    ``are_variants(a, b)`` and ``are_variants(b, a)`` always agree.
    """
    left, right = fold(first), fold(second)
    if not left or not right:
        return False
    if left == right:
        return True
    return right in variants_of(left)


def share_initial(first: str, second: str) -> bool:
    """True when two given names start with the same letter.

    Weak evidence on its own, which is why it scores far below a known variant.
    """
    left, right = fold(first), fold(second)
    return bool(left) and bool(right) and left[0] == right[0]


def group_count() -> int:
    """Number of distinct names the table knows. Used by tests and the UI."""
    return len(_table())


def all_names() -> Iterable[str]:
    return sorted(_table())


def clear_cache() -> None:
    """Forget the loaded table, so an edit takes effect without a restart."""
    _load.cache_clear()
