"""Shared types for source adapters.

An adapter turns one file into standardized records. It reports problems as findings -
a rule code plus the values to fill its message with - rather than raising flags
itself, so the adapter can be tested without the rule machinery and the caller stays
in charge of what becomes a flag.
"""

from __future__ import annotations

from sot.rules.model import Finding

#: Historical name. Findings are not adapter-specific - identity resolution raises
#: them too - so the type itself lives with the rest of the flag vocabulary.
AdapterFinding = Finding

__all__ = ["AdapterFinding", "Finding"]
