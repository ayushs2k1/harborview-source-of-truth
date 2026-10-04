"""Resolving raw values to canonical codes through a pack crosswalk."""

from __future__ import annotations

from collections.abc import Iterable

from sot.canon import squeeze
from sot.ingest.contracts import Crosswalk, header_key
from sot.normalize.result import Normalized, Quality, empty, invalid, ok, repaired

#: Rule code raised when a value is not in the crosswalk, by crosswalk name.
UNKNOWN_CODES = {
    "facilities": "CODE_UNKNOWN_FACILITY",
    "roles": "CODE_UNKNOWN_ROLE",
}


def resolve_code(
    raw: object,
    crosswalk: Crosswalk | None,
    *,
    ambiguous_values: Iterable[str] = (),
) -> Normalized[str]:
    """Map a raw value to its canonical code.

    A value the crosswalk lists as ambiguous - a job title like "Nurse", which could be
    any of three roles - resolves to nothing here on purpose. Guessing would put hours
    in the wrong staffing category, and the person's own credential settles it properly
    later on.
    """
    if raw is None:
        return empty("")
    text = squeeze(str(raw))
    if not text:
        return empty(str(raw))
    if crosswalk is None:
        return invalid(text, "no crosswalk is configured for this field")

    key = header_key(text)
    if key in {header_key(value) for value in ambiguous_values}:
        return Normalized(
            None,
            Quality.AMBIGUOUS,
            f"{text!r} does not identify a role on its own; "
            "it is resolved from the person's credential instead",
            text,
        )

    code = crosswalk.resolve(text)
    if code is None:
        return invalid(
            text,
            f"{text!r} is not in the {crosswalk.name} crosswalk",
            code=UNKNOWN_CODES.get(crosswalk.name),
        )
    if code != text:
        return repaired(code, text, f"{text!r} mapped to {code}")
    return ok(code, text)
