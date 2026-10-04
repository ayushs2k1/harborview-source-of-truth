"""Three-valued logic.

Spec principle 6: unknown is never green. Checks return pass, fail, or unknown, and the
difference is load-bearing for compliance - "we could not tell whether this nurse was
licensed" is a different statement from "this nurse was licensed", and only one of them
is safe to show as a tick. Keeping it a real type rather than ``bool | None`` means the
combinators get written once, here, instead of being re-derived at each call site.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Tri(StrEnum):
    """Kleene three-valued truth.

    A ``StrEnum`` so that it round-trips through DuckDB and JSON as its own name:
    ``UNKNOWN`` has to stay readable wherever it surfaces.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"

    @property
    def is_green(self) -> bool:
        """True only for :attr:`PASS`. Unknown is never green."""
        return self is Tri.PASS

    @property
    def is_known(self) -> bool:
        """True when the check reached a verdict either way."""
        return self is not Tri.UNKNOWN

    def __invert__(self) -> Tri:
        """Negation, with unknown preserved."""
        if self is Tri.PASS:
            return Tri.FAIL
        if self is Tri.FAIL:
            return Tri.PASS
        return Tri.UNKNOWN


def from_bool(value: bool | None) -> Tri:
    """Lift an optional boolean, where ``None`` means "could not determine"."""
    if value is None:
        return Tri.UNKNOWN
    return Tri.PASS if value else Tri.FAIL


def tri_all(values: Iterable[Tri]) -> Tri:
    """Kleene conjunction: any fail wins, then any unknown, else pass.

    An empty input is :attr:`Tri.UNKNOWN` rather than vacuously true. "Every worked day
    is covered by a valid credential" must not pass when there are no worked days on
    record, because the usual reason for that is a source that failed to load.
    """
    seen_unknown = False
    seen_any = False
    for value in values:
        seen_any = True
        if value is Tri.FAIL:
            return Tri.FAIL
        if value is Tri.UNKNOWN:
            seen_unknown = True
    if not seen_any:
        return Tri.UNKNOWN
    return Tri.UNKNOWN if seen_unknown else Tri.PASS


def tri_any(values: Iterable[Tri]) -> Tri:
    """Kleene disjunction: any pass wins, then any unknown, else fail.

    An empty input is :attr:`Tri.UNKNOWN`, for the same reason as :func:`tri_all`.
    """
    seen_unknown = False
    seen_any = False
    for value in values:
        seen_any = True
        if value is Tri.PASS:
            return Tri.PASS
        if value is Tri.UNKNOWN:
            seen_unknown = True
    if not seen_any:
        return Tri.UNKNOWN
    return Tri.UNKNOWN if seen_unknown else Tri.FAIL
