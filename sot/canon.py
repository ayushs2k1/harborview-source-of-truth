"""Canonical serialization, ordering, and rounding.

Everything that becomes an identifier, a hash input, or a persisted output passes
through here. The point is principle 9 of the spec: the same files, decisions, and
as-of date must produce identical output in any file order, on any machine, in any
process. Dict insertion order, set iteration order, and float accumulation error are
the three ways that quietly stops being true, so they are all handled in one place.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")

#: Hours are stored at this precision. Clock arithmetic in minutes over a 24h day
#: cannot need more, and fixing it here keeps 7.999999999 out of the database.
HOURS_PRECISION = 4


def _default(value: Any) -> Any:
    """Render types that ``json`` cannot, deterministically."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (set, frozenset)):
        return sorted(canonical_json(item) for item in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize ``value`` to JSON with sorted keys and no incidental whitespace."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_default,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """UTF-8 bytes of :func:`canonical_json`, the input to every hash we take."""
    return canonical_json(value).encode("utf-8")


def sort_records(records: Iterable[T], *keys: str) -> list[T]:
    """Sort mappings or objects by the named attributes, nulls last and stable.

    Used wherever an unordered collection is about to become output. Missing and
    ``None`` values sort after present ones so that a partially populated record
    cannot change the order of the rest.
    """

    def sort_key(record: Any) -> tuple:
        parts: list[tuple] = []
        for key in keys:
            raw = record.get(key) if isinstance(record, Mapping) else getattr(record, key, None)
            parts.append(_NULL_KEY if raw is None else (0, *_sort_key(raw)))
        return tuple(parts)

    return sorted(records, key=sort_key)


#: Sorts after every present value, whatever its type.
_NULL_KEY = (1, 9, 0.0, "")


def _sort_key(value: Any) -> tuple[int, float, str]:
    """Order values predictably across mixed types.

    Numbers compare as numbers rather than as text, so 2 precedes 10 and -1 precedes
    both. Types that cannot be compared to each other are separated by the leading
    rank instead of raising, because a column with mixed content still has to sort.
    """
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float, Decimal)):
        return (0, float(value), "")
    if isinstance(value, (datetime, date, time)):
        return (1, 0.0, value.isoformat())
    if isinstance(value, Enum):
        return (2, 0.0, str(value.value))
    return (2, 0.0, str(value))


def dedupe(values: Iterable[T]) -> list[T]:
    """Remove duplicates while preserving first-seen order.

    The order-preserving form matters: ``sorted(set(...))`` would reorder values whose
    sequence carries meaning, and plain ``set(...)`` is non-deterministic in output.
    """
    seen: set[Any] = set()
    out: list[T] = []
    for value in values:
        marker = (
            value
            if isinstance(value, (str, int, float, bool, type(None)))
            else canonical_json(value)
        )
        if marker in seen:
            continue
        seen.add(marker)
        out.append(value)
    return out


def round_hours(value: float | int | Decimal | None) -> float | None:
    """Round an hours quantity to :data:`HOURS_PRECISION`, or return ``None``."""
    if value is None:
        return None
    as_float = float(value)
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return round(as_float, HOURS_PRECISION)


def sum_hours(values: Iterable[float | int | Decimal | None]) -> float:
    """Total an hours series deterministically.

    Summed in sorted order and rounded once at the end, so that the same multiset of
    segments gives the same total no matter which order they arrived in.
    """
    cleaned = [float(v) for v in values if v is not None]
    cleaned.sort()
    return round(math.fsum(cleaned), HOURS_PRECISION)


def nfkd_fold(text: str) -> str:
    """Strip accents and compatibility forms, for comparison keys only.

    Never use the result for display: it turns ``Peña`` into ``pena``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def squeeze(text: str) -> str:
    """Collapse runs of whitespace and trim, leaving internal single spaces."""
    return " ".join(text.split())


def as_tuple(value: Any) -> tuple:
    """Coerce a scalar or sequence into a tuple, treating strings as scalars."""
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        return (value,)
    return tuple(value)
