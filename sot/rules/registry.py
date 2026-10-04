"""The rule registry.

Every finding the system can produce is declared here as data: its severity, who owns
it, what it means, and the sentence it says. Three things follow from that.

Rules are documented automatically - ``docs/RULES.md`` is generated from the registry,
so the documentation cannot drift from the code. The chaos deck can assert coverage,
because the list of codes that *should* exist is queryable rather than implicit. And
wording lives in one place, so a message can be improved without hunting through the
module that happens to raise it.

Severity is a function of context, not a constant. "Scheduled but not in HR" is a
warning for a kitchen porter and a critical finding for a nurse, so a spec may carry a
``severity_fn`` that reads the flag's own parameters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sot.rules.model import Aggregate, Category, OwnerRole, Severity


@dataclass(frozen=True)
class RuleSpec:
    """Everything known about one rule before it fires."""

    code: str
    severity: Severity
    category: Category
    priority: str  # P0 | P1 | P2
    meaning: str
    title: str
    message: str
    suggested_action: str
    owner_role: OwnerRole
    aggregate: Aggregate = Aggregate.NONE
    #: Returns the severity for one occurrence, given its params. Overrides `severity`.
    severity_fn: Callable[[dict[str, Any]], Severity] | None = None
    #: Human-readable note about conditional severity, for the generated docs.
    severity_note: str = ""
    #: False while only the metadata exists. Lets the coverage report list the gap.
    implemented: bool = False
    #: Pack keys this rule reads, recorded so the docs can say what is configurable.
    params_from_pack: tuple[str, ...] = field(default_factory=tuple)

    def severity_for(self, params: dict[str, Any]) -> Severity:
        """Severity for one occurrence."""
        if self.severity_fn is None:
            return self.severity
        try:
            return self.severity_fn(params)
        except Exception:
            # A rule that cannot work out its own severity still has to produce a
            # flag: principle 1 says nothing crashes the run, including the rules.
            return self.severity


class RuleRegistry:
    """A collection of rule specs, keyed by code."""

    def __init__(self) -> None:
        self._rules: dict[str, RuleSpec] = {}

    def register(self, spec: RuleSpec) -> RuleSpec:
        """Add a spec. Duplicate codes are a programming error, not a runtime one."""
        if spec.code in self._rules:
            raise ValueError(f"rule {spec.code} is already registered")
        self._rules[spec.code] = spec
        return spec

    def register_all(self, specs: Iterable[RuleSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, code: str) -> RuleSpec:
        """Look up a spec, with a message that names the mistake."""
        try:
            return self._rules[code]
        except KeyError:
            raise KeyError(
                f"unknown rule code {code!r}. Add it to sot/rules/catalog.py so that it "
                "appears in the generated documentation and the coverage report."
            ) from None

    def has(self, code: str) -> bool:
        return code in self._rules

    def codes(self) -> list[str]:
        """Every registered code, sorted."""
        return sorted(self._rules)

    def all(self) -> list[RuleSpec]:
        """Every spec, ordered by category then severity then code."""
        return sorted(
            self._rules.values(),
            key=lambda s: (str(s.category), s.severity.rank, s.code),
        )

    def by_category(self, category: Category) -> list[RuleSpec]:
        return [spec for spec in self.all() if spec.category is category]

    def by_priority(self, priority: str) -> list[RuleSpec]:
        return [spec for spec in self.all() if spec.priority == priority]

    def unimplemented(self, priority: str | None = None) -> list[str]:
        """Codes that exist as metadata but have no evaluator yet."""
        return sorted(
            spec.code
            for spec in self._rules.values()
            if not spec.implemented and (priority is None or spec.priority == priority)
        )
