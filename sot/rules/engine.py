"""Running the rules.

Every rule is a function from the whole picture to a list of findings. They are
registered against the codes they can raise, which means the catalog knows which codes
have an evaluator and which are still only declared - so "what is left to build" is a
query rather than a note in a file somewhere.

Rules run in registration order and each is wrapped: one that raises becomes a
BLOCKER naming itself, and the others still run. A rule with a bug should cost its own
findings, not the whole report.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sot.ingest.contracts import Pack
from sot.ledger.authority import Authority
from sot.ledger.claims import Claim
from sot.ledger.golden import Credential, Golden, PayLine
from sot.match.fourway import MatchResult
from sot.rules.model import Entity, Finding

Evaluator = Callable[["RuleContext"], Iterable[Finding]]


@dataclass
class RuleContext:
    """Everything a rule may look at."""

    as_of: date
    pack: Pack
    authority: Authority
    persons: Sequence[Any] = ()
    golden: Golden = field(default_factory=lambda: Golden(()))
    claims: Sequence[Claim] = ()
    credentials: Sequence[Credential] = ()
    pay_lines: Sequence[PayLine] = ()
    segments: Sequence[Mapping[str, Any]] = ()
    match: MatchResult = field(default_factory=MatchResult)
    daily_hours: Sequence[Any] = ()
    #: (facility, date) -> residents, when a census was supplied.
    census: Mapping[tuple[str, date], int] = field(default_factory=dict)
    vendor_documents: Sequence[Mapping[str, Any]] = ()

    def __post_init__(self) -> None:
        self._by_person = {getattr(person, "person_id", ""): person for person in self.persons}

    # -- lookups -----------------------------------------------------------

    def display_name(self, person_id: str) -> str:
        person = self._by_person.get(person_id)
        return getattr(person, "display_name", "") or person_id

    def person(self, person_id: str) -> Any:
        return self._by_person.get(person_id)

    def entity(self, person_id: str) -> Entity:
        return Entity("person", person_id, self.display_name(person_id))

    def setting(self, dotted: str, default: Any = None) -> Any:
        return self.pack.setting(dotted, default)

    def credentials_for(self, person_id: str) -> list[Credential]:
        return [credential for credential in self.credentials if credential.holder_id == person_id]

    def role_requires_credential(self, role: str) -> tuple[str, ...]:
        """Credential types that satisfy a role, per the pack."""
        required = self.setting("required_credential", {}) or {}
        values = required.get((role or "").upper())
        return tuple(str(item).upper() for item in values) if values else ()

    def facilities(self) -> list[str]:
        crosswalk = self.pack.crosswalk("facilities")
        return sorted(entry.code for entry in crosswalk.entries) if crosswalk else []

    def facility_name(self, code: str) -> str:
        crosswalk = self.pack.crosswalk("facilities")
        if crosswalk is None:
            return code
        entry = crosswalk.by_code().get(code)
        return entry.name if entry and entry.name else code

    def pbj_code(self, role: str) -> str:
        crosswalk = self.pack.crosswalk("roles")
        if crosswalk is None:
            return ""
        entry = crosswalk.by_code().get((role or "").upper())
        return entry.extra.get("pbj_code", "") if entry else ""


@dataclass(frozen=True)
class Registration:
    """One evaluator and the codes it may raise."""

    name: str
    codes: tuple[str, ...]
    function: Evaluator


_REGISTRY: list[Registration] = []


def evaluator(*codes: str) -> Callable[[Evaluator], Evaluator]:
    """Register a rule function against the codes it can raise."""

    def decorate(function: Evaluator) -> Evaluator:
        _REGISTRY.append(Registration(function.__name__, tuple(codes), function))
        return function

    return decorate


def registrations() -> list[Registration]:
    """Every registered evaluator, in registration order."""
    return list(_REGISTRY)


def registered_codes() -> set[str]:
    """Codes that have an evaluator behind them."""
    return {code for registration in _REGISTRY for code in registration.codes}


def run_rules(context: RuleContext) -> list[Finding]:
    """Run every rule, surviving any that breaks."""
    findings: list[Finding] = []
    for registration in _REGISTRY:
        try:
            findings.extend(registration.function(context) or ())
        except Exception as exc:
            findings.append(
                Finding(
                    "NODE_FAILED",
                    {
                        "label": f"the {registration.name} rule",
                        "node_id": registration.name,
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc()[-2000:],
                    },
                    key_parts=(registration.name,),
                )
            )
    return findings


def load_rule_modules() -> None:
    """Import the rule modules so their registrations happen.

    Called once from the pipeline. Keeping it explicit rather than importing at
    package level means a test can register its own rules without the real catalog
    running too.
    """
    from sot.rules import (  # noqa: F401
        cross_source_rules,
        domain_healthcare,
        time_rules,
    )
