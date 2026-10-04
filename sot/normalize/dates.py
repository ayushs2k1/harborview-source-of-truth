"""Parsing dates out of whatever the exporting system produced.

Compliance is judged as of the date of the work, so a date read wrongly is not a
cosmetic problem - it decides whether somebody was licensed on the day they worked.
The two dangerous cases are handled explicitly rather than guessed at: a spreadsheet
that exported its date column as numbers, and ``03/04`` meaning either the third of
April or the fourth of March.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

from sot.canon import squeeze
from sot.normalize.result import Normalized, ambiguous, empty, invalid, ok, repaired

#: Excel counts days from this date. It is two days before 1900-01-01 because the
#: format preserves a 1900 leap year that never happened, from Lotus 1-2-3.
EXCEL_EPOCH = date(1899, 12, 30)

#: Serial numbers only within living memory are treated as dates. Outside this, a bare
#: number in a date column is more likely an identifier than a date.
EXCEL_SERIAL_MIN = 30000  # 1982
EXCEL_SERIAL_MAX = 60000  # 2064

#: Two-digit years at or above this are last century. Standard spreadsheet behaviour.
YEAR_PIVOT = 70

ORDER_MDY = "MDY"
ORDER_DMY = "DMY"

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    # Spanish, since the roster will contain Spanish names and may contain Spanish dates.
    "ene": 1,
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abr": 4,
    "abril": 4,
    "mayo": 5,
    "jun.": 6,
    "junio": 6,
    "julio": 7,
    "ago": 8,
    "agosto": 8,
    "septiembre": 9,
    "set": 9,
    "octubre": 10,
    "noviembre": 11,
    "dic": 12,
    "diciembre": 12,
}

_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$")
_DAY_MONTH_YEAR_TEXT = re.compile(r"^(\d{1,2})[-\s]([A-Za-zÁ-úá-ú.]+)[-,\s]+(\d{2,4})$")
_MONTH_DAY_YEAR_TEXT = re.compile(
    r"^([A-Za-zÁ-úá-ú.]+)[-\s]+(\d{1,2})(?:st|nd|rd|th)?[-,\s]+(\d{2,4})$"
)
_SERIAL = re.compile(r"^\d{4,6}(?:\.0+)?$")
_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _expand_year(value: int) -> int:
    """Turn a two-digit year into a four-digit one, pivoting at 70."""
    if value >= 1000:
        return value
    return 1900 + value if value >= YEAR_PIVOT else 2000 + value


def _build(year: int, month: int, day: int) -> date | None:
    """Construct a date, or ``None`` if those numbers are not one."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(
    raw: object,
    *,
    order: str = ORDER_MDY,
    order_basis: str = "the pack default",
) -> Normalized[date]:
    """Parse one date.

    ``order`` resolves day/month ambiguity and should come from the column's own
    unambiguous values where there are any - see :func:`infer_order`. The basis is
    carried into the note so the flag can say *why* that order was assumed.
    """
    if raw is None:
        return empty("")
    if isinstance(raw, date):
        return ok(raw, str(raw))
    text = squeeze(str(raw))
    if not text:
        return empty(str(raw))

    compact = _COMPACT.match(text)
    if compact:
        year, month, day = (int(part) for part in compact.groups())
        built = _build(year, month, day)
        if built:
            return repaired(built, text, "read as a compact YYYYMMDD date")

    if _SERIAL.match(text):
        number = int(float(text))
        if EXCEL_SERIAL_MIN <= number <= EXCEL_SERIAL_MAX:
            converted = EXCEL_EPOCH + timedelta(days=number)
            return repaired(
                converted,
                text,
                f"spreadsheet date serial {number} read as {converted.isoformat()}",
                code="EXCEL_SERIAL_DATE",
            )
        return invalid(text, f"{text} is not a date", code="DATE_UNPARSEABLE")

    iso = _ISO.match(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        built = _build(year, month, day)
        if built:
            return ok(built, text)
        return invalid(text, f"{text} is not a real date", code="DATE_IMPOSSIBLE")

    numeric = _NUMERIC.match(text)
    if numeric:
        first, second, year_raw = (int(part) for part in numeric.groups())
        year = _expand_year(year_raw)
        month_first = _build(year, first, second)
        day_first = _build(year, second, first)

        if month_first and not day_first:
            return ok(month_first, text)
        if day_first and not month_first:
            return ok(day_first, text)
        if not month_first and not day_first:
            return invalid(text, f"{text} is not a real date", code="DATE_IMPOSSIBLE")
        if month_first == day_first:
            return ok(month_first, text)
        chosen = month_first if order == ORDER_MDY else day_first
        return ambiguous(
            chosen,
            text,
            f"{text} could be read either way round; {order} assumed from {order_basis}",
            code="DATE_AMBIGUOUS_ASSUMED",
        )

    textual = _DAY_MONTH_YEAR_TEXT.match(text)
    if textual:
        day_raw, month_name, year_raw = textual.groups()
        month = MONTHS.get(month_name.strip(".").lower())
        if month:
            built = _build(_expand_year(int(year_raw)), month, int(day_raw))
            if built:
                return repaired(built, text, "read as day-month-year")
            return invalid(text, f"{text} is not a real date", code="DATE_IMPOSSIBLE")

    textual = _MONTH_DAY_YEAR_TEXT.match(text)
    if textual:
        month_name, day_raw, year_raw = textual.groups()
        month = MONTHS.get(month_name.strip(".").lower())
        if month:
            built = _build(_expand_year(int(year_raw)), month, int(day_raw))
            if built:
                return repaired(built, text, "read as month-day-year")
            return invalid(text, f"{text} is not a real date", code="DATE_IMPOSSIBLE")

    return invalid(text, f"{text!r} is not a date", code="DATE_UNPARSEABLE")


def infer_order(values: Iterable[object]) -> tuple[str | None, str]:
    """Work out a column's day/month order from the values that cannot be ambiguous.

    One date with a 13th or higher in the first position settles the whole column. This
    is worth far more than any default, because it is evidence from the data rather
    than an assumption about the exporting system.

    Returns the order and a short description of what decided it.
    """
    saw_day_first = False
    saw_month_first = False
    for value in values:
        text = squeeze(str(value or ""))
        match = _NUMERIC.match(text)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 and second <= 12:
            saw_day_first = True
        elif second > 12 and first <= 12:
            saw_month_first = True

    if saw_day_first and saw_month_first:
        # Both orders appear in one column, so the export is internally inconsistent.
        # Neither can be trusted; fall back to the pack default and say so.
        return (None, "the column contains dates in both orders")
    if saw_day_first:
        return (ORDER_DMY, "another date in this column has a day above 12")
    if saw_month_first:
        return (ORDER_MDY, "another date in this column has a month above 12")
    return (None, "")


def month_end(value: date) -> date:
    """Last day of the month containing ``value``."""
    following = value.replace(day=28) + timedelta(days=4)
    return following - timedelta(days=following.day)


def is_month_end(value: date) -> bool:
    return value == month_end(value)
