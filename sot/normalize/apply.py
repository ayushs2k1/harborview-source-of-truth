"""Applying a contract's declared types to the values in a file.

The contract says a column holds dates, hours, a name, or a code; this turns that into
a call to the right normalizer with the right context. Context is the point: a date
column is read as a whole before any single value in it is parsed, because one date
with a day above twelve settles the order for every other date in the column, and that
is evidence rather than an assumption.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sot.ingest.contracts import Column, Contract, Pack
from sot.normalize import dates as dates_module
from sot.normalize.codes import resolve_code
from sot.normalize.hours import parse_hours
from sot.normalize.ids_licenses import parse_credential_number
from sot.normalize.names import parse_name
from sot.normalize.phones import parse_phone
from sot.normalize.result import Normalized, empty, ok

#: Contract column types this module knows how to normalize. Anything else is left as
#: trimmed text, which is the right answer for a free-text column.
KNOWN_TYPES = frozenset(
    {"date", "hours", "integer", "person_name", "phone", "license_number", "code"}
)


@dataclass
class FileContext:
    """What a whole file tells us about how to read its individual values."""

    date_order: str = dates_module.ORDER_MDY
    date_order_basis: str = "the pack default"
    #: Per-column overrides, where a column settles its own order.
    column_date_order: dict[str, tuple[str, str]] = field(default_factory=dict)

    def order_for(self, column: str) -> tuple[str, str]:
        return self.column_date_order.get(column, (self.date_order, self.date_order_basis))


def build_context(
    contract: Contract, values_by_column: Mapping[str, Sequence[str]], pack: Pack
) -> FileContext:
    """Work out per-column reading rules before parsing any single value."""
    default_order = str(pack.setting("date_order_default", dates_module.ORDER_MDY)).upper()
    context = FileContext(date_order=default_order, date_order_basis="the pack default")
    for column in contract.columns:
        if column.type != "date":
            continue
        order, basis = dates_module.infer_order(values_by_column.get(column.name, ()))
        if order:
            context.column_date_order[column.name] = (order, basis)
    return context


def _credential_prefixes(pack: Pack) -> dict[str, tuple[str, ...]]:
    """Credential type to the number prefixes it may carry, from the pack crosswalk."""
    crosswalk = pack.crosswalk("credential_types")
    if crosswalk is None:
        return {}
    table: dict[str, tuple[str, ...]] = {}
    for entry in crosswalk.entries:
        raw = entry.extra.get("number_prefixes", "")
        prefixes = tuple(part.strip().upper() for part in raw.split("|") if part.strip())
        if prefixes:
            table[entry.code.upper()] = prefixes
    return table


def normalize_value(
    column: Column,
    raw: str,
    *,
    pack: Pack,
    context: FileContext,
    row: Mapping[str, str] | None = None,
) -> Normalized[Any]:
    """Normalize one cell according to its contract column."""
    if raw is None or not str(raw).strip():
        return empty(str(raw or ""))

    if column.type == "date":
        order, basis = context.order_for(column.name)
        return dates_module.parse_date(raw, order=order, order_basis=basis)

    if column.type == "hours":
        return parse_hours(raw)

    if column.type == "integer":
        try:
            return ok(int(float(str(raw).replace(",", ""))), str(raw))
        except (TypeError, ValueError):
            from sot.normalize.result import invalid

            return invalid(str(raw), f"{raw!r} is not a whole number")

    if column.type == "person_name":
        return parse_name(raw)

    if column.type == "phone":
        return parse_phone(raw)

    if column.type == "license_number":
        row = row or {}
        declared = str(row.get("license_type") or row.get("credential_type") or "")
        credential_type = ""
        if declared:
            crosswalk = pack.crosswalk("credential_types")
            credential_type = (crosswalk.resolve(declared) or "") if crosswalk else declared.upper()
        return parse_credential_number(
            raw, credential_type=credential_type, prefixes_by_type=_credential_prefixes(pack)
        )

    if column.type == "code" and column.crosswalk:
        ambiguous_values: Iterable[str] = ()
        if column.crosswalk == "roles":
            ambiguous_values = pack.setting("ambiguous_role_titles", []) or []
        return resolve_code(
            raw, pack.crosswalk(column.crosswalk), ambiguous_values=ambiguous_values
        )

    return ok(str(raw).strip(), str(raw))


def render(value: Any) -> str:
    """Store a normalized value as text, in a form that reads back unambiguously."""
    from datetime import date as date_type

    from sot.normalize.ids_licenses import CredentialNumber
    from sot.normalize.names import PersonName
    from sot.normalize.phones import Phone

    if value is None:
        return ""
    if isinstance(value, date_type):
        return value.isoformat()
    if isinstance(value, PersonName):
        return value.display
    if isinstance(value, Phone):
        return value.digits
    if isinstance(value, CredentialNumber):
        return value.normalized
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def derived_fields(column: Column, value: Any) -> dict[str, str]:
    """Extra fields a normalizer produces beyond the main value.

    A parsed name is worth far more than its display form - the comparison key and the
    separate parts are what identity resolution actually matches on - so they are
    stored alongside rather than recomputed everywhere.
    """
    from sot.normalize.ids_licenses import CredentialNumber
    from sot.normalize.names import PersonName
    from sot.normalize.phones import Phone

    prefix = column.name
    if isinstance(value, PersonName):
        return {
            f"{prefix}__key": value.key,
            f"{prefix}__given": value.given,
            f"{prefix}__family": value.family,
            f"{prefix}__middle": value.middle,
            f"{prefix}__suffix": value.suffix,
        }
    if isinstance(value, Phone):
        return {f"{prefix}__display": value.display, f"{prefix}__key": value.key}
    if isinstance(value, CredentialNumber):
        return {
            f"{prefix}__key": value.key,
            f"{prefix}__digits": value.digits,
            f"{prefix}__prefix": value.prefix,
        }
    return {}
