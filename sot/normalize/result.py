"""What every normalizer returns.

Spec section 7: a normalizer returns the value, a quality, and a note. The quality is
what lets the system distinguish "this was fine", "we tidied it up", "we had to guess",
and "this is not a value at all" - four outcomes that deserve four different responses
and would otherwise collapse into a silent ``None``.

A normalizer also names the rule its outcome should raise, as a plain string. The
caller decides whether to raise it, which keeps the normalizers free of any dependency
on the rule machinery while keeping the mapping in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class Quality(StrEnum):
    """How much the normalizer had to do, and how far to trust the result."""

    OK = "ok"
    #: Understood, but the input needed fixing first. Reported in aggregate.
    REPAIRED = "repaired"
    #: Understood only by making an assumption. The assumption is in the note.
    AMBIGUOUS = "ambiguous"
    #: Not a value of this type. The field ends up empty and dependent checks unknown.
    INVALID = "invalid"

    @property
    def is_trustworthy(self) -> bool:
        return self in (Quality.OK, Quality.REPAIRED)


@dataclass(frozen=True)
class Normalized(Generic[T]):
    """A normalized value with its provenance."""

    value: T | None
    quality: Quality = Quality.OK
    note: str = ""
    raw: str = ""
    #: Rule code the caller should raise for this outcome, if any.
    code: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None and self.quality.is_trustworthy

    @property
    def is_empty(self) -> bool:
        return self.value is None and self.quality is Quality.OK

    def __bool__(self) -> bool:
        return self.value is not None


def empty(raw: str = "") -> Normalized[T]:
    """Nothing to normalize. Not an error: a blank optional field is fine."""
    return Normalized(None, Quality.OK, "", raw)


def ok(value: T, raw: str = "", note: str = "") -> Normalized[T]:
    return Normalized(value, Quality.OK, note, raw)


def repaired(value: T, raw: str, note: str, code: str | None = "VALUE_NORMALIZED") -> Normalized[T]:
    return Normalized(value, Quality.REPAIRED, note, raw, code)


def ambiguous(value: T, raw: str, note: str, code: str | None = None) -> Normalized[T]:
    return Normalized(value, Quality.AMBIGUOUS, note, raw, code)


def invalid(raw: str, note: str, code: str | None = None) -> Normalized[T]:
    return Normalized(None, Quality.INVALID, note, raw, code)
