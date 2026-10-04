"""Shared types for source adapters.

An adapter turns one file into standardized records. It reports problems as findings -
a rule code plus the values to fill its message with - rather than raising flags
itself, so the adapter can be tested without the rule machinery and the caller stays
in charge of what becomes a flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AdapterFinding:
    """Something the adapter wants reported."""

    code: str
    params: dict[str, Any] = field(default_factory=dict)
    page: int | None = None
    row_index: int | None = None
    column: str | None = None
    raw_value: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    #: Identity of the finding, when the default (page and column) is not specific enough.
    key_parts: tuple[str, ...] = ()
