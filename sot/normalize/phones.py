"""Phone numbers.

Only lightly load-bearing on its own - but two people sharing a number is a duplicate
record or a household, and both are worth knowing about, so the number has to reduce to
a comparable form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sot.canon import squeeze
from sot.normalize.result import Normalized, empty, invalid, ok, repaired

#: North American numbering: area and exchange codes never start with 0 or 1.
_VALID_NANP = re.compile(r"^[2-9]\d{2}[2-9]\d{6}$")
_EXTENSION = re.compile(r"(?:x|ext\.?|extension|#)\s*(\d{1,6})\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Phone:
    digits: str
    extension: str = ""

    @property
    def display(self) -> str:
        if len(self.digits) == 10:
            formatted = f"({self.digits[:3]}) {self.digits[3:6]}-{self.digits[6:]}"
        else:
            formatted = self.digits
        return f"{formatted} x{self.extension}" if self.extension else formatted

    @property
    def key(self) -> str:
        """Comparison form. The extension is excluded: a shared switchboard line with
        different extensions is not two people sharing a phone."""
        return self.digits


def parse_phone(raw: object) -> Normalized[Phone]:
    """Reduce a phone number to ten digits plus an optional extension."""
    if raw is None:
        return empty("")
    text = squeeze(str(raw))
    if not text:
        return empty(str(raw))

    extension = ""
    match = _EXTENSION.search(text)
    if match:
        extension = match.group(1)
        text = text[: match.start()].strip()

    digits = re.sub(r"\D", "", text)
    if not digits:
        return invalid(str(raw), f"{raw!r} contains no digits", code="PHONE_INVALID")

    changed = digits != re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
        changed = True

    if len(digits) != 10 or not _VALID_NANP.match(digits):
        return invalid(
            str(raw),
            f"{raw!r} is not a usable ten-digit number",
            code="PHONE_INVALID",
        )

    phone = Phone(digits=digits, extension=extension)
    if changed or extension or phone.display != str(raw).strip():
        return repaired(phone, str(raw), f"reformatted as {phone.display}")
    return ok(phone, str(raw))
