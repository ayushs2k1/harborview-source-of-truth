"""Hour quantities.

Payroll exports write the same number half a dozen ways. All of them have to reduce to
one float, because the four-way match is arithmetic and a string that silently became
zero would show up as a staffing shortfall that is not real.
"""

from __future__ import annotations

import re

from sot.canon import round_hours, squeeze
from sot.normalize.result import Normalized, Quality, empty, invalid, ok, repaired

_HOURS_MINUTES = re.compile(r"^(-?\d+)\s*[:.]\s*([0-5]\d)$")
#: "36h 30m", "36 hr 30 min", "40 hours". The unit may be a bare h, which is why the
#: r is optional - without that, "36h 30m" reads as nothing at all.
_H_AND_M = re.compile(
    r"^(-?\d+(?:\.\d+)?)\s*h(?:ou)?r?s?\.?\s*(?:(\d{1,2})\s*m(?:in)?s?\.?)?$", re.I
)
_PLAIN = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(?:h|hr|hrs|hour|hours)?\.?$", re.I)
#: A comma followed by exactly three digits is a thousands separator, not a decimal.
_THOUSANDS = re.compile(r"^(-?\d{1,3}(?:,\d{3})+)(\.\d+)?$")


def parse_hours(raw: object) -> Normalized[float]:
    """Parse an hours value in any of the forms an export produces."""
    if raw is None:
        return empty("")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        value = round_hours(float(raw))
        return _check_sign(value, str(raw), changed=False)
    text = squeeze(str(raw))
    if not text:
        return empty(str(raw))

    thousands = _THOUSANDS.match(text)
    if thousands:
        merged = thousands.group(1).replace(",", "") + (thousands.group(2) or "")
        return _check_sign(
            round_hours(float(merged)), text, changed=True, note=f"read {text} as {merged}"
        )

    match = _HOURS_MINUTES.match(text)
    if match:
        whole, minutes = int(match.group(1)), int(match.group(2))
        sign = -1 if text.lstrip().startswith("-") else 1
        value = round_hours(abs(whole) + minutes / 60.0)
        return _check_sign(
            round_hours(sign * (value or 0.0)),
            text,
            changed=True,
            note=f"read {text} as {sign * (value or 0.0)} hours",
        )

    match = _H_AND_M.match(text)
    if match:
        whole = float(match.group(1))
        minutes = int(match.group(2) or 0)
        sign = -1 if whole < 0 else 1
        value = round_hours(abs(whole) + minutes / 60.0)
        return _check_sign(
            round_hours(sign * (value or 0.0)),
            text,
            changed=True,
            note=f"read {text} as {sign * (value or 0.0)} hours",
        )

    match = _PLAIN.match(text)
    if match:
        body = match.group(1)
        # A comma with one or two digits after it is a decimal comma: 36,5 is 36.5.
        normalized = body.replace(",", ".") if "," in body else body
        try:
            value = round_hours(float(normalized))
        except ValueError:
            return invalid(text, f"{raw!r} is not a number of hours", code="HOURS_UNPARSEABLE")
        return _check_sign(value, text, changed=normalized != text)

    return invalid(text, f"{raw!r} is not a number of hours", code="HOURS_UNPARSEABLE")


def _check_sign(
    value: float | None, raw: str, *, changed: bool, note: str = ""
) -> Normalized[float]:
    if value is None:
        return invalid(raw, f"{raw!r} is not a number of hours", code="HOURS_UNPARSEABLE")
    if value < 0:
        # Kept, not discarded: a negative row is usually a correction to an earlier
        # period, and dropping it would leave the earlier overpayment uncorrected.
        return Normalized(
            value,
            Quality.AMBIGUOUS,
            f"{raw} is negative; usually a reversal of an earlier period",
            raw,
            "HOURS_NEGATIVE",
        )
    if changed:
        return repaired(value, raw, note or f"read {raw} as {value} hours")
    return ok(value, raw)
