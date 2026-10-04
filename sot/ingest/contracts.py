"""Source contracts: what a file of each type is expected to look like.

A contract is the pack's description of one source - its canonical column names, the
spellings a real export might use instead, the type of each value, and which columns
the file is useless without. Everything in ingestion reads from here: classification
scores a file against every contract, header mapping resolves one file against the
winner, and the reader uses the types to decide what a value means.

Nothing in this module knows anything about healthcare. The vocabulary comes from the
pack, which is what lets a different industry reuse the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sot.canon import nfkd_fold

#: Engine-level roles a pack's source can play. The rest of the pipeline keys off
#: these rather than off the pack's own source names, which is what lets a trucking
#: dispatch file reuse the nodes written for a nursing rota.
SOURCE_ROLES = ("roster", "payroll", "credentials", "schedule", "census", "vendor_documents")


def header_key(text: str) -> str:
    """Comparison key for a column heading.

    Lowercased, accent-folded, and stripped of everything but letters and digits, so
    ``Pay Period Start``, ``pay_period_start`` and ``PayPeriodStart`` all agree.
    """
    folded = nfkd_fold(str(text)).lower()
    return "".join(ch for ch in folded if ch.isalnum())


@dataclass(frozen=True)
class Column:
    """One canonical field, and the spellings that mean it."""

    name: str
    type: str = "string"
    required: bool = False
    synonyms: tuple[str, ...] = ()
    crosswalk: str | None = None
    description: str = ""

    @property
    def keys(self) -> tuple[str, ...]:
        """Every accepted spelling, as comparison keys, canonical name first."""
        return tuple(
            dict.fromkeys([header_key(self.name), *(header_key(s) for s in self.synonyms)])
        )


@dataclass(frozen=True)
class Contract:
    """One source's expected shape."""

    source: str
    role: str
    grain: str = ""
    description: str = ""
    columns: tuple[Column, ...] = ()
    #: Alternative sets of columns, at least one of which must be fully present.
    requires_any: tuple[tuple[str, ...], ...] = ()
    path: Path | None = None

    @property
    def by_name(self) -> dict[str, Column]:
        return {column.name: column for column in self.columns}

    @property
    def required_columns(self) -> tuple[Column, ...]:
        return tuple(column for column in self.columns if column.required)

    def column_for_key(self, key: str) -> Column | None:
        """Exact synonym lookup. Returns the first column claiming this spelling."""
        for column in self.columns:
            if key in column.keys:
                return column
        return None

    def missing_required(self, mapped: set[str]) -> list[str]:
        """Required columns absent from ``mapped``, honouring ``requires_any``.

        A roster with one ``Name`` column instead of separate given and family names is
        still a usable roster, so alternatives are expressed as groups rather than by
        making everything optional.
        """
        missing = [c.name for c in self.required_columns if c.name not in mapped]
        if not self.requires_any:
            return missing
        satisfied = any(all(name in mapped for name in group) for group in self.requires_any)
        if satisfied:
            # An alternative group covers the gap; drop any required column that the
            # satisfied group replaces.
            alternatives = {name for group in self.requires_any for name in group}
            return [name for name in missing if name not in alternatives]
        return missing or [" or ".join(group) for group in self.requires_any[:1]]


@dataclass(frozen=True)
class CrosswalkEntry:
    """One canonical code and the raw values that mean it."""

    code: str
    name: str = ""
    aliases: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Crosswalk:
    """A named set of code mappings, e.g. facilities or roles."""

    name: str
    entries: tuple[CrosswalkEntry, ...] = ()

    @property
    def lookup(self) -> dict[str, str]:
        """Comparison key to canonical code, including the code and name themselves."""
        table: dict[str, str] = {}
        for entry in self.entries:
            for raw in (entry.code, entry.name, *entry.aliases):
                if raw:
                    table.setdefault(header_key(raw), entry.code)
        return table

    def resolve(self, raw: str) -> str | None:
        """Canonical code for a raw value, or ``None`` if it is not in the crosswalk."""
        return self.lookup.get(header_key(raw)) if raw else None

    def by_code(self) -> dict[str, CrosswalkEntry]:
        return {entry.code: entry for entry in self.entries}


@dataclass(frozen=True)
class Pack:
    """A loaded domain pack: settings, contracts, and crosswalks."""

    id: str
    settings: dict[str, Any]
    contracts: tuple[Contract, ...]
    crosswalks: dict[str, Crosswalk]
    path: Path

    def contract(self, source: str) -> Contract | None:
        return next((c for c in self.contracts if c.source == source), None)

    def contracts_for_role(self, role: str) -> tuple[Contract, ...]:
        return tuple(c for c in self.contracts if c.role == role)

    def crosswalk(self, name: str) -> Crosswalk | None:
        return self.crosswalks.get(name)

    def setting(self, dotted: str, default: Any = None) -> Any:
        """Read a nested setting by dotted path, e.g. ``pbj.daily_cap_hours``."""
        node: Any = self.settings
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _load_contract(path: Path) -> Contract:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    columns = tuple(
        Column(
            name=str(item["name"]),
            type=str(item.get("type", "string")),
            required=bool(item.get("required", False)),
            synonyms=tuple(str(s) for s in item.get("synonyms", ())),
            crosswalk=item.get("crosswalk"),
            description=str(item.get("description", "")),
        )
        for item in data.get("columns", [])
    )
    role = str(data.get("role", data.get("source", "")))
    if role not in SOURCE_ROLES:
        raise ValueError(
            f"{path}: role {role!r} is not one of {SOURCE_ROLES}. The engine keys its "
            "nodes off roles, so a new one needs engine support, not just config."
        )
    return Contract(
        source=str(data.get("source", path.stem)),
        role=role,
        grain=str(data.get("grain", "")),
        description=str(data.get("description", "")),
        columns=columns,
        requires_any=tuple(tuple(str(n) for n in group) for group in data.get("requires_any", ())),
        path=path,
    )


def _load_crosswalk(path: Path) -> Crosswalk:
    import csv

    entries: list[CrosswalkEntry] = []
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            known = {"code", "name", "aliases"}
            entries.append(
                CrosswalkEntry(
                    code=(row.get("code") or "").strip(),
                    name=(row.get("name") or "").strip(),
                    aliases=tuple(
                        alias.strip()
                        for alias in (row.get("aliases") or "").split("|")
                        if alias.strip()
                    ),
                    extra={
                        key: (value or "").strip()
                        for key, value in row.items()
                        if key and key not in known
                    },
                )
            )
    return Crosswalk(name=path.stem, entries=tuple(entries))


@lru_cache(maxsize=8)
def load_pack(pack_id: str, packs_dir: str | None = None) -> Pack:
    """Load a pack by id. Cached, since a run reads it many times."""
    from sot.config import settings

    base = Path(packs_dir) if packs_dir else settings().packs_dir
    root = base / pack_id
    manifest = root / "pack.yaml"
    if not manifest.is_file():
        raise FileNotFoundError(f"no pack.yaml in {root}")

    contracts = tuple(_load_contract(path) for path in sorted((root / "contracts").glob("*.yaml")))
    crosswalks = {
        path.stem: _load_crosswalk(path) for path in sorted((root / "crosswalks").glob("*.csv"))
    }
    return Pack(
        id=pack_id,
        settings=yaml.safe_load(manifest.read_text(encoding="utf-8")) or {},
        contracts=contracts,
        crosswalks=crosswalks,
        path=root,
    )


def clear_pack_cache() -> None:
    """Forget loaded packs, so an edit takes effect without a restart."""
    load_pack.cache_clear()
