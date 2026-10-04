"""Flag vocabulary: severities, categories, evidence, and the flag itself.

A flag is the system's only output that a human reads directly, so the shape here is
the shape of the product. Spec section 12 fixes the fields; this module makes them a
type so that a rule cannot forget the suggested action or invent a new severity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from sot.ids import flag_id


class Severity(StrEnum):
    """How much attention a finding deserves.

    Ordered deliberately: ``sorted`` on the enum gives inbox order.
    """

    BLOCKER = "BLOCKER"
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        """Lower sorts first. Used for inbox ordering and for 'worst severity' checks."""
        return _SEVERITY_RANK[self]

    @property
    def is_above_info(self) -> bool:
        """True for anything a human has to look at. The clean-set gate uses this."""
        return self is not Severity.INFO


_SEVERITY_RANK = {
    Severity.BLOCKER: 0,
    Severity.CRITICAL: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}


class Category(StrEnum):
    """Where in the pipeline a finding came from. Drives the inbox filters."""

    FILE = "FILE"
    FORMAT = "FORMAT"
    IDENTITY = "IDENTITY"
    CROSS_SOURCE = "CROSS_SOURCE"
    TIME = "TIME"
    PDF = "PDF"
    DOMAIN = "DOMAIN"


class OwnerRole(StrEnum):
    """Who can actually fix it.

    A flag with no owner is a flag nobody acts on, which is why this is required
    rather than optional.
    """

    HR = "HR"
    PAYROLL = "PAYROLL"
    DON = "DON"
    ADMINISTRATOR = "ADMINISTRATOR"
    DATA_STEWARD = "DATA_STEWARD"


class Aggregate(StrEnum):
    """How many flags one rule may produce.

    Informational findings are usually true of a whole column at once. Twenty-three
    separate "value reformatted" cards would bury the one that says someone worked
    without a licence, so those roll up into a single flag carrying a count.
    """

    NONE = "none"
    BY_COLUMN = "by_column"
    BY_FILE = "by_file"
    BY_RUN = "by_run"


class FlagStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


@dataclass(frozen=True)
class Entity:
    """Something a flag is about, rendered as a chip that links to its page."""

    type: str  # person | facility | credential | file | org
    id: str
    display: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id, "display": self.display or self.id}


@dataclass(frozen=True)
class Evidence:
    """A pointer at the characters that caused the finding.

    Tabular sources fill ``row_index`` and ``column_name``; PDFs fill ``page`` and the
    bounding box so the viewer can draw a rectangle on the page image.
    """

    file_id: str | None = None
    source_type: str | None = None
    row_index: int | None = None
    page: int | None = None
    column_name: str | None = None
    raw_value: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    def as_row(self, run_id: str, flag: str, seq: int) -> dict[str, Any]:
        """Flatten for the ``flag_evidence`` table."""
        x0, top, x1, bottom = self.bbox or (None, None, None, None)
        return {
            "run_id": run_id,
            "flag_id": flag,
            "seq": seq,
            "file_id": self.file_id,
            "source_type": self.source_type,
            "row_index": self.row_index,
            "page": self.page,
            "column_name": self.column_name,
            "raw_value": self.raw_value,
            "x0": x0,
            "top": top,
            "x1": x1,
            "bottom": bottom,
        }

    def key(self) -> str:
        """Short identity used when hashing a flag id."""
        parts = [
            self.file_id or "",
            str(self.row_index) if self.row_index is not None else "",
            str(self.page) if self.page is not None else "",
            self.column_name or "",
        ]
        return "|".join(parts)


@dataclass(frozen=True)
class Finding:
    """Something a pipeline step wants reported.

    A rule code plus the values its message needs. Steps return these rather than
    building flags themselves, so they can be tested without the rule machinery and
    the decision about severity stays in one place.
    """

    code: str
    params: dict[str, Any] = field(default_factory=dict)
    page: int | None = None
    row_index: int | None = None
    column: str | None = None
    raw_value: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    entities: tuple[Entity, ...] = ()
    #: Identity of the finding, when the default is not specific enough.
    key_parts: tuple[str, ...] = ()


@dataclass
class Flag:
    """One finding, with everything a human needs to act on it."""

    rule_code: str
    severity: Severity
    category: Category
    title: str
    message: str
    suggested_action: str
    owner_role: OwnerRole
    entities: list[Entity] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    status: FlagStatus = FlagStatus.OPEN
    dismiss_reason: str | None = None
    due_date: date | None = None
    occurrence_count: int = 1
    node_id: str | None = None
    #: Explicit identity. Defaults to entities plus evidence locations.
    key_parts: tuple[str, ...] = ()

    @property
    def flag_id(self) -> str:
        """Stable across runs: the same problem in the same data keeps its id."""
        keys = self.key_parts or tuple(f"{e.type}:{e.id}" for e in self.entities)
        return flag_id(self.rule_code, keys, [ev.key() for ev in self.evidence[:5]])

    def as_row(self, run_id: str) -> dict[str, Any]:
        """Flatten for the ``flags`` table."""
        from sot.canon import canonical_json

        return {
            "run_id": run_id,
            "flag_id": self.flag_id,
            "rule_code": self.rule_code,
            "severity": str(self.severity),
            "category": str(self.category),
            "title": self.title,
            "message": self.message,
            "entities_json": canonical_json([e.as_dict() for e in self.entities]),
            "suggested_action": self.suggested_action,
            "owner_role": str(self.owner_role),
            "due_date": self.due_date,
            "status": str(self.status),
            "dismiss_reason": self.dismiss_reason,
            "occurrence_count": self.occurrence_count,
            "node_id": self.node_id,
            "params_json": canonical_json(self.params),
        }
