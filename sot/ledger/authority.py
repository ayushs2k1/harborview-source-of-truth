"""Survivorship configuration: which source wins, per attribute.

The ledger keeps everything. This decides only which value the golden record shows,
and the losing claims stay beside the winner - which is what lets the person page
display "HR says this, the verification service says that" rather than silently
picking one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Tie-breaks, in the order they are applied after source authority.
TIE_OBSERVED_ON = "observed_on"
TIE_COMPLETENESS = "completeness"
TIE_CLAIM_ID = "claim_id"

DEFAULT_ORDER = ("roster", "credentials", "payroll", "schedule")


@dataclass(frozen=True)
class ConflictGroup:
    """Attributes describing one real-world fact, and what to raise when they differ."""

    name: str
    attributes: tuple[str, ...]
    rule: str


@dataclass(frozen=True)
class Authority:
    """A pack's survivorship rules."""

    default_order: tuple[str, ...] = DEFAULT_ORDER
    orders: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    tie_breakers: tuple[str, ...] = (TIE_OBSERVED_ON, TIE_COMPLETENESS, TIE_CLAIM_ID)
    conflict_groups: tuple[ConflictGroup, ...] = ()
    conflict_within: Mapping[str, str] = field(default_factory=dict)

    def order_for(self, attribute: str) -> tuple[str, ...]:
        """Source roles for an attribute, most authoritative first."""
        return tuple(self.orders.get(attribute, self.default_order))

    def rank(self, attribute: str, source_role: str) -> int:
        """Position of a source for an attribute. Unlisted sources sort last."""
        order = self.order_for(attribute)
        try:
            return order.index(source_role)
        except ValueError:
            return len(order) + 1

    def attributes(self) -> tuple[str, ...]:
        return tuple(sorted(self.orders))


def load_authority(path: str | Path) -> Authority:
    """Read ``authority.yaml``. A pack without one gets sensible defaults."""
    source = Path(path)
    if not source.is_file():
        return Authority()
    data: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8")) or {}

    groups = tuple(
        ConflictGroup(
            name=name,
            attributes=tuple(str(item) for item in (spec or {}).get("attributes", ())),
            rule=str((spec or {}).get("rule", "")),
        )
        for name, spec in sorted((data.get("conflict_groups") or {}).items())
        if (spec or {}).get("rule")
    )
    return Authority(
        default_order=tuple(data.get("default") or DEFAULT_ORDER),
        orders={
            str(name): tuple(str(role) for role in roles)
            for name, roles in (data.get("attributes") or {}).items()
        },
        tie_breakers=tuple(
            data.get("tie_breakers") or (TIE_OBSERVED_ON, TIE_COMPLETENESS, TIE_CLAIM_ID)
        ),
        conflict_groups=groups,
        conflict_within={
            str(name): str(rule) for name, rule in (data.get("conflict_within") or {}).items()
        },
    )


def authority_for_pack(pack: Any) -> Authority:
    """Load the authority file sitting beside a pack's manifest."""
    return load_authority(Path(pack.path) / "authority.yaml")


def sort_key(authority: Authority, attribute: str) -> Any:
    """Sort key putting the winning claim first.

    Source authority decides; the tie-breaks only matter when two sources of equal
    standing both have a value, which in practice means HR exported twice.
    """

    def key(claim: Any) -> tuple:
        parts: list[Any] = [authority.rank(attribute, claim.source_role)]
        for breaker in authority.tie_breakers:
            if breaker == TIE_OBSERVED_ON:
                # Later observations first; a missing date sorts last.
                parts.append(-claim.observed_on.toordinal() if claim.observed_on else float("inf"))
            elif breaker == TIE_COMPLETENESS:
                parts.append(0 if (claim.value_norm or "").strip() else 1)
            else:
                parts.append(claim.claim_id)
        return tuple(parts)

    return key


def deciding_rule(authority: Authority, attribute: str, winner: Any, others: Sequence[Any]) -> str:
    """Which step actually settled it, for the golden record to record."""
    if not others:
        return "only claim"
    best_rank = authority.rank(attribute, winner.source_role)
    if all(authority.rank(attribute, claim.source_role) > best_rank for claim in others):
        return f"source authority ({winner.source_role})"
    dated = [claim for claim in others if claim.observed_on]
    if (
        winner.observed_on
        and all(winner.observed_on >= claim.observed_on for claim in dated)
        and dated
    ):
        return "most recently observed"
    if (winner.value_norm or "").strip() and any(
        not (claim.value_norm or "").strip() for claim in others
    ):
        return "most complete"
    return "stable tie-break"
