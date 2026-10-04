"""Credential numbers.

The credential number is the strongest link in the whole system: it is the one field
that ties a person in the roster to a verified licence, regardless of what either
system calls them. So it has to survive being retyped - lowercased, de-hyphenated,
with a prefix dropped, or with an O typed where a zero belongs.

The comparison key is the credential type plus the digits. The prefix is evidence
about the type rather than part of the identity, which is what lets the same number
match whether it arrives with its prefix, without it, or in lower case - while a
prefix that contradicts its recorded type stays visible as a finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sot.canon import squeeze
from sot.normalize.result import Normalized, Quality, empty, invalid, ok, repaired

#: Letters that get typed for digits inside a number. Applied only to the digit part.
LOOKALIKES = {"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}

_SPLIT = re.compile(r"^([A-Z.]*)[\s\-_/]*([0-9A-Z]*)$")


@dataclass(frozen=True)
class CredentialNumber:
    raw: str
    prefix: str = ""
    digits: str = ""
    credential_type: str = ""

    @property
    def normalized(self) -> str:
        """Canonical written form: the prefix, a hyphen, then the digits."""
        return f"{self.prefix}-{self.digits}" if self.prefix else self.digits

    @property
    def key(self) -> str:
        """Comparison key: type and digits. The prefix is evidence, not identity."""
        return f"{self.credential_type or self.prefix}:{self.digits}".upper()


def parse_credential_number(
    raw: object,
    *,
    credential_type: str = "",
    prefixes_by_type: dict[str, tuple[str, ...]] | None = None,
) -> Normalized[CredentialNumber]:
    """Normalize a credential number and check its prefix against its type."""
    if raw is None:
        return empty("")
    text = squeeze(str(raw)).upper()
    if not text:
        return empty(str(raw))

    cleaned = re.sub(r"[\s\-_/.]", "", text)
    if not cleaned:
        return invalid(str(raw), f"{raw!r} has no usable characters")

    match = re.match(r"^([A-Z]*)(.*)$", cleaned)
    prefix, remainder = (match.group(1), match.group(2)) if match else ("", cleaned)

    notes: list[str] = []
    code: str | None = None
    swapped = "".join(LOOKALIKES.get(ch, ch) for ch in remainder)
    if swapped != remainder:
        changes = sorted({f"{a}->{LOOKALIKES[a]}" for a in remainder if a in LOOKALIKES})
        notes.append(f"look-alike characters read as digits ({', '.join(changes)})")
        code = "LICENSE_NUMBER_CHAR_CONFUSION"
    digits = swapped

    if not digits.isdigit():
        return invalid(str(raw), f"{raw!r} has no digits once the prefix is removed")

    prefixes_by_type = prefixes_by_type or {}
    resolved_type = credential_type.upper()

    if not prefix and resolved_type:
        inferred = prefixes_by_type.get(resolved_type, ())
        if inferred:
            prefix = inferred[0]
            notes.append(f"prefix {prefix} inferred from the credential type")

    if prefix and resolved_type:
        allowed = {value.upper() for value in prefixes_by_type.get(resolved_type, ())}
        if allowed and prefix not in allowed:
            # The number itself is perfectly readable; what is wrong is that the prefix
            # and the recorded type disagree, and we cannot tell which one is the error.
            # The value is kept so the rest of the pipeline can still use the digits.
            return Normalized(
                CredentialNumber(str(raw), prefix, digits, resolved_type),
                Quality.AMBIGUOUS,
                f"prefix {prefix} does not match credential type {resolved_type}",
                str(raw),
                "LICENSE_PREFIX_TYPE_MISMATCH",
            )

    if not resolved_type and prefix:
        for type_code, prefixes in sorted(prefixes_by_type.items()):
            if prefix in {value.upper() for value in prefixes}:
                resolved_type = type_code
                break

    number = CredentialNumber(
        raw=str(raw), prefix=prefix, digits=digits, credential_type=resolved_type
    )
    note = "; ".join(notes)
    if notes or number.normalized != str(raw).strip().upper():
        return repaired(number, str(raw), note or f"written as {number.normalized}", code=code)
    return ok(number, str(raw))
