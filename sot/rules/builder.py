"""Building flags from rule specs.

Two jobs. First, turn a rule code plus some values into a finished flag: severity
resolved, message written, evidence attached. Second, roll up the informational rules
so the inbox stays readable - twenty-three "value reformatted" cards would bury the one
that says somebody worked without a licence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from sot.rules.catalog import RULES
from sot.rules.model import (
    Aggregate,
    Entity,
    Evidence,
    Flag,
    Severity,
)
from sot.rules.registry import RuleRegistry

#: Evidence pointers kept per flag. Enough to show the pattern, few enough to render.
MAX_EVIDENCE = 5


#: An ISO date sitting in a message parameter.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def humanize(value: Any) -> Any:
    """Render a value the way a flag message should read.

    A date becomes "Mar 3, 2027" rather than its ISO form. These messages are read
    by a director of nursing between shifts, not by a machine, and the ISO form
    makes every sentence read like a log line.
    """
    from datetime import date as date_type

    if isinstance(value, date_type):
        return f"{value:%b} {value.day}, {value.year}"
    if isinstance(value, str) and _ISO_DATE.match(value):
        try:
            parsed = date_type.fromisoformat(value)
        except ValueError:
            return value
        return f"{parsed:%b} {parsed.day}, {parsed.year}"
    return value


class _SafeDict(dict):
    """Leaves unknown placeholders visible instead of raising.

    A rule that forgets a parameter should produce a slightly odd sentence, not an
    exception that loses the finding entirely.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_message(template: str, params: dict[str, Any]) -> str:
    """Fill a message template as far as the given values allow."""
    params = {key: humanize(value) for key, value in params.items()}
    try:
        return template.format_map(_SafeDict(params))
    except (ValueError, TypeError, IndexError, KeyError):
        # A format spec that does not fit its value (``{n:.0%}`` given a string, say).
        # Strip the specs and substitute what we can rather than lose the message.
        def substitute(match: re.Match[str]) -> str:
            return str(params.get(match.group(1), match.group(0)))

        return re.sub(r"\{(\w+)(?::[^}]*)?\}", substitute, template)


class FlagCollector:
    """Gathers flags during a run and finalizes them at the end."""

    def __init__(self, registry: RuleRegistry | None = None) -> None:
        self.registry = registry or RULES
        self._flags: list[Flag] = []
        self._aggregates: dict[tuple, Flag] = {}

    # -- raising -----------------------------------------------------------

    def raise_flag(
        self,
        code: str,
        params: dict[str, Any] | None = None,
        *,
        entities: Sequence[Entity] = (),
        evidence: Sequence[Evidence] = (),
        key_parts: Sequence[str] = (),
        node_id: str | None = None,
        severity: Severity | None = None,
    ) -> Flag:
        """Raise one finding. Returns the flag, already aggregated if the rule says so."""
        spec = self.registry.get(code)
        values = dict(params or {})
        resolved = severity or spec.severity_for(values)

        if spec.aggregate is not Aggregate.NONE:
            return self._aggregate(spec, values, evidence, node_id, resolved)

        flag = Flag(
            rule_code=code,
            severity=resolved,
            category=spec.category,
            title=spec.title,
            message=format_message(spec.message, values),
            suggested_action=spec.suggested_action,
            owner_role=spec.owner_role,
            entities=list(entities),
            evidence=list(evidence)[:MAX_EVIDENCE],
            params=values,
            node_id=node_id,
            key_parts=tuple(key_parts),
        )
        self._flags.append(flag)
        return flag

    def _scope(self, spec, params: dict[str, Any], evidence: Sequence[Evidence]) -> tuple:
        """Identity of the bucket an aggregated finding belongs to."""
        first = evidence[0] if evidence else None
        file_id = params.get("file_id") or (first.file_id if first else None)
        if spec.aggregate is Aggregate.BY_COLUMN:
            column = params.get("column") or (first.column_name if first else None)
            return (spec.code, file_id, column)
        if spec.aggregate is Aggregate.BY_FILE:
            return (spec.code, file_id)
        return (spec.code,)

    def _aggregate(
        self,
        spec,
        params: dict[str, Any],
        evidence: Sequence[Evidence],
        node_id: str | None,
        severity: Severity,
    ) -> Flag:
        """Merge into the bucket for this rule's scope, creating it if needed."""
        scope = self._scope(spec, params, evidence)
        increment = int(params.get("count", 1) or 1)
        existing = self._aggregates.get(scope)

        if existing is None:
            flag = Flag(
                rule_code=spec.code,
                severity=severity,
                category=spec.category,
                title=spec.title,
                message="",  # written at finalize, once the count is final
                suggested_action=spec.suggested_action,
                owner_role=spec.owner_role,
                evidence=list(evidence)[:MAX_EVIDENCE],
                params={**params, "count": increment},
                node_id=node_id,
                key_parts=tuple(str(part) for part in scope if part is not None),
            )
            self._aggregates[scope] = flag
            self._flags.append(flag)
            return flag

        existing.params["count"] = int(existing.params.get("count", 1)) + increment
        existing.occurrence_count = existing.params["count"]
        # The worst severity seen wins; an aggregate must not hide its worst member.
        if severity.rank < existing.severity.rank:
            existing.severity = severity
        for item in evidence:
            if len(existing.evidence) < MAX_EVIDENCE:
                existing.evidence.append(item)
        return existing

    # -- finishing ---------------------------------------------------------

    def finalize(self) -> list[Flag]:
        """Write the aggregate messages and return every flag in inbox order."""
        for flag in self._aggregates.values():
            flag.occurrence_count = int(flag.params.get("count", 1))
        for flag in self._flags:
            if not flag.message:
                spec = self.registry.get(flag.rule_code)
                flag.message = format_message(spec.message, flag.params)
        return sorted(
            self._flags,
            key=lambda f: (f.severity.rank, f.rule_code, f.flag_id),
        )

    # -- inspection --------------------------------------------------------

    @property
    def flags(self) -> list[Flag]:
        return list(self._flags)

    def codes(self) -> list[str]:
        """Distinct rule codes raised, sorted. Handy in tests."""
        return sorted({flag.rule_code for flag in self._flags})

    def worst_severity(self) -> Severity | None:
        if not self._flags:
            return None
        return min((flag.severity for flag in self._flags), key=lambda s: s.rank)

    def counts_by_severity(self) -> dict[str, int]:
        counts = {str(severity): 0 for severity in Severity}
        for flag in self._flags:
            counts[str(flag.severity)] += 1
        return counts

    def above_info(self) -> list[Flag]:
        """Everything a human has to look at. The clean-set gate reads this."""
        return [flag for flag in self.finalize() if flag.severity.is_above_info]

    def extend(self, flags: Iterable[Flag]) -> None:
        self._flags.extend(flags)
