"""The shift grammar.

One parser, shared by every pack. A printed rota writes the same eight-hour shift as
``7a-3p``, ``7A-3P``, ``7:00 AM - 3:00 PM``, ``0700-1500`` or just ``7-3``, and a cell
may hold a double, an absence code, or a star somebody added by hand. All of it has to
reduce to segments with real timestamps, because the hours that come out of here are
the hours that get reported to the regulator.

Two rules decide the length of a segment, in this order. The page's own footnote wins
where it speaks - it is the facility telling us what its shifts are worth, breaks
included. Otherwise the clock decides, and we say so, because a shift with an unpaid
break will read long.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from sot.canon import round_hours, squeeze
from sot.normalize.result import Normalized, Quality, ambiguous, invalid, ok

#: Every dash a printed schedule might use, mapped to a plain hyphen.
DASHES = "".join(
    chr(code) for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFF00 + 0x0D)
)

#: Separators between two shifts in one cell.
_DOUBLE_SEPARATORS = re.compile(r"\s*[/,&+]\s*|\s+and\s+", re.IGNORECASE)

_TIME_MERIDIEM = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?\s*m?\.?$", re.IGNORECASE)
_TIME_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_MILITARY = re.compile(r"^(\d{3,4})$")
_TIME_BARE = re.compile(r"^(\d{1,2})$")

_TRAILING_SYMBOLS = re.compile(r"[\s*#†‡!~]+$")
_TRAILING_PARENS = re.compile(r"\s*\([^)]{1,8}\)\s*$")
_TRAILING_WORD = re.compile(r"\s+([A-Za-z]{1,4})$")

#: Longest a single segment may plausibly be. Beyond this the reading is wrong, not
#: the roster: a 20-hour shift is a parse error in everything but name.
MAX_SEGMENT_HOURS = 16.0


class ShiftCategory(StrEnum):
    """What a cell says the person was doing."""

    WORK = "WORK"
    PTO = "PTO"
    TRAINING = "TRAINING"
    ONCALL = "ONCALL"
    OFF = "OFF"

    @property
    def is_worked(self) -> bool:
        """Training counts as worked for reconciling against payroll; whether it counts
        towards reported staffing is a pack setting, applied later."""
        return self in (ShiftCategory.WORK, ShiftCategory.TRAINING)


#: Default cell codes. Packs override these; these are the shapes seen everywhere.
DEFAULT_SHIFT_CODES: dict[str, tuple[str, ...]] = {
    "off": ("OFF", "O", "X", "-", "--", "N/A", "RDO"),
    "pto": (
        "PTO",
        "VAC",
        "VACATION",
        "SICK",
        "SL",
        "HOL",
        "HOLIDAY",
        "LOA",
        "FMLA",
        "BRV",
        "BEREAVEMENT",
        "JURY",
        "LEAVE",
    ),
    "training": ("ORIENT", "ORIENTATION", "TRN", "TRAINING", "INSERVICE", "IN-SERVICE", "EDU"),
    "oncall": ("OC", "ON CALL", "ONCALL", "CALL", "STANDBY"),
}

_CATEGORY_BY_GROUP = {
    "off": ShiftCategory.OFF,
    "pto": ShiftCategory.PTO,
    "training": ShiftCategory.TRAINING,
    "oncall": ShiftCategory.ONCALL,
}


@dataclass(frozen=True)
class ShiftSegment:
    """One continuous stretch of time."""

    token: str
    start: time
    end: time
    overnight: bool
    clock_hours: float
    hours: float
    hours_source: str = "clock"  # clock | footnote

    def timestamps(self, work_date: date) -> tuple[datetime, datetime]:
        """Absolute start and end, rolling over midnight where the shift does."""
        start = datetime.combine(work_date, self.start)
        end_date = work_date + timedelta(days=1) if self.overnight else work_date
        return (start, datetime.combine(end_date, self.end))


@dataclass(frozen=True)
class CellParse:
    """What one cell of the rota turned out to mean."""

    raw: str
    category: ShiftCategory
    segments: tuple[ShiftSegment, ...] = ()
    markers: tuple[str, ...] = ()
    code: str = ""

    @property
    def total_hours(self) -> float:
        return round_hours(sum(segment.hours for segment in self.segments)) or 0.0

    @property
    def is_worked(self) -> bool:
        return self.category.is_worked and bool(self.segments)


@dataclass(frozen=True)
class FootnoteTable:
    """Shift lengths as the page itself defines them."""

    by_times: dict[tuple[time, time], float] = field(default_factory=dict)
    tokens: tuple[tuple[str, float], ...] = ()
    text: str = ""

    def hours_for(self, start: time, end: time) -> float | None:
        return self.by_times.get((start, end))

    def candidates(self) -> tuple[tuple[time, time], ...]:
        return tuple(self.by_times)

    def __bool__(self) -> bool:
        return bool(self.by_times)


def normalize_dashes(text: str) -> str:
    """Replace every dash variant with a plain hyphen and collapse repeats."""
    for dash in DASHES:
        text = text.replace(dash, "-")
    return re.sub(r"-{2,}", "-", text)


def _parse_time(text: str) -> tuple[time | None, bool]:
    """Parse one side of a range. Returns the time and whether am/pm was explicit."""
    cleaned = squeeze(text).strip().lower()
    if not cleaned:
        return (None, False)

    match = _TIME_MERIDIEM.match(cleaned)
    if match:
        hour, minute, half = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if hour == 12:
            hour = 0
        if half == "p":
            hour += 12
        if hour > 23 or minute > 59:
            return (None, True)
        return (time(hour, minute), True)

    match = _TIME_CLOCK.match(cleaned)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return (None, True)
        # A 24-hour clock reading is unambiguous; a 12-hour one without am/pm is not.
        return (time(hour, minute), hour > 12 or hour == 0)

    match = _TIME_MILITARY.match(cleaned)
    if match:
        digits = match.group(1).zfill(4)
        hour, minute = int(digits[:2]), int(digits[2:])
        if hour > 23 or minute > 59:
            return (None, True)
        return (time(hour, minute), True)

    match = _TIME_BARE.match(cleaned)
    if match:
        hour = int(match.group(1))
        if hour > 23:
            return (None, True)
        return (time(hour % 24, 0), False)

    return (None, False)


def clock_hours(start: time, end: time) -> float:
    """Length of a stretch from ``start`` to ``end``, rolling over midnight.

    Equal times mean a full day rather than nothing. That is almost certainly a
    mistake in the source, and reporting 24 hours gets it caught by the daily cap;
    reporting zero would hide it.
    """
    minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
    if minutes <= 0:
        minutes += 24 * 60
    return round_hours(minutes / 60.0) or 0.0


def _strip_markers(text: str) -> tuple[str, list[str]]:
    """Peel hand-written annotations off the end of a cell."""
    markers: list[str] = []
    working = text.strip()
    for _ in range(3):
        match = _TRAILING_PARENS.search(working)
        if match:
            markers.insert(0, match.group(0).strip())
            working = working[: match.start()].strip()
            continue
        match = _TRAILING_SYMBOLS.search(working)
        if match and match.group(0).strip():
            markers.insert(0, match.group(0).strip())
            working = working[: match.start()].strip()
            continue
        break
    return (working, markers)


def _parse_range(
    token: str, footnote: FootnoteTable | None
) -> tuple[ShiftSegment | None, bool, str]:
    """Parse one ``start-end`` range. Returns the segment, whether we had to guess,
    and a note."""
    parts = [part for part in token.split("-") if part.strip()]
    if len(parts) != 2:
        return (None, False, "")

    start, start_explicit = _parse_time(parts[0])
    end, end_explicit = _parse_time(parts[1])
    if start is None or end is None:
        return (None, False, "")

    guessed = False
    note = ""
    if not start_explicit and not end_explicit:
        resolved = _resolve_from_footnote(start, end, footnote)
        if resolved is not None:
            start, end = resolved
            guessed = True
            note = f"{token} read as {_render(start)}-{_render(end)} from the page footnote"
        else:
            # No footnote to lean on. The overwhelmingly common reading of a bare
            # range on a rota is a day shift: morning start, afternoon finish.
            morning, afternoon = start, time((end.hour % 12) + 12, end.minute)
            if 0 < clock_hours(morning, afternoon) <= MAX_SEGMENT_HOURS:
                start, end = morning, afternoon
                guessed = True
                note = f"{token} read as a day shift, {_render(start)}-{_render(end)}"
            else:
                return (None, False, "")

    hours = clock_hours(start, end)
    source = "clock"
    if footnote:
        defined = footnote.hours_for(start, end)
        if defined is not None:
            hours = defined
            source = "footnote"

    segment = ShiftSegment(
        token=token,
        start=start,
        end=end,
        overnight=end <= start,
        clock_hours=clock_hours(start, end),
        hours=hours,
        hours_source=source,
    )
    return (segment, guessed, note)


def _resolve_from_footnote(
    start: time, end: time, footnote: FootnoteTable | None
) -> tuple[time, time] | None:
    """Match a bare ``7-3`` against the shifts the page says it runs."""
    if not footnote:
        return None
    matches = [
        (candidate_start, candidate_end)
        for candidate_start, candidate_end in footnote.candidates()
        if candidate_start.hour % 12 == start.hour % 12
        and candidate_end.hour % 12 == end.hour % 12
        and candidate_start.minute == start.minute
        and candidate_end.minute == end.minute
    ]
    return matches[0] if len(matches) == 1 else None


def _render(value: time) -> str:
    """Write a time the way a rota does: ``7a``, ``3p``, ``11:30p``."""
    half = "a" if value.hour < 12 else "p"
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d}{half}" if value.minute else f"{hour}{half}"


def build_codes(overrides: Mapping[str, Iterable[str]] | None = None) -> dict[str, frozenset[str]]:
    """Cell codes for a pack, folded for comparison."""
    merged = {group: set(values) for group, values in DEFAULT_SHIFT_CODES.items()}
    for group, values in (overrides or {}).items():
        merged.setdefault(group, set()).update(values)
    return {
        group: frozenset(squeeze(str(value)).upper() for value in values)
        for group, values in merged.items()
    }


def parse_shift_cell(
    raw: object,
    *,
    footnote: FootnoteTable | None = None,
    codes: Mapping[str, frozenset[str]] | None = None,
) -> Normalized[CellParse]:
    """Parse one cell of a weekly rota."""
    codes = codes or build_codes()
    if raw is None:
        return ok(CellParse("", ShiftCategory.OFF), "")
    text = squeeze(normalize_dashes(str(raw)))
    if not text:
        return ok(CellParse(str(raw), ShiftCategory.OFF), str(raw))

    body, markers = _strip_markers(text)
    upper = body.upper()

    for group, values in codes.items():
        if upper in values:
            category = _CATEGORY_BY_GROUP.get(group)
            if category is None:
                continue
            parsed = CellParse(text, category, markers=tuple(markers), code=upper)
            return ok(parsed, str(raw))

    if not body:
        return ok(CellParse(text, ShiftCategory.OFF, markers=tuple(markers)), str(raw))

    tokens = [part for part in _DOUBLE_SEPARATORS.split(body) if part.strip()]
    segments: list[ShiftSegment] = []
    notes: list[str] = []
    guessed = False
    for token in tokens:
        segment, token_guessed, note = _parse_range(token.strip(), footnote)
        if segment is None:
            # Retry once with a trailing word treated as an annotation: "7a-3p CN".
            retry = _TRAILING_WORD.sub("", token.strip())
            if retry != token.strip():
                segment, token_guessed, note = _parse_range(retry, footnote)
                if segment is not None:
                    markers.append(token.strip()[len(retry) :].strip())
        if segment is None:
            return invalid(
                str(raw),
                f"{raw!r} is not a shift or a known absence code",
                code="SHIFT_UNPARSEABLE",
            )
        segments.append(segment)
        guessed = guessed or token_guessed
        if note:
            notes.append(note)

    parsed = CellParse(text, ShiftCategory.WORK, tuple(segments), tuple(markers))
    if guessed:
        return ambiguous(parsed, str(raw), "; ".join(notes), code="SHIFT_AMBIGUOUS_ASSUMED")
    if markers:
        return Normalized(
            parsed, Quality.REPAIRED, f"annotation {' '.join(markers)} kept as a note", str(raw)
        )
    return ok(parsed, str(raw))


#: "... are 8 hours", "... is 7.5 hrs". The number and the word, wherever they sit.
_HOURS_PHRASE = re.compile(r"\b(?:is|are)\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b", re.IGNORECASE)

#: A time range anywhere in the text.
_RANGE_IN_TEXT = re.compile(
    r"(\d{1,2}(?::\d{2})?\s*[apAP]?\.?\s*[mM]?\.?)\s*-\s*"
    r"(\d{1,2}(?::\d{2})?\s*[apAP]?\.?\s*[mM]?\.?)"
)

#: Clause boundaries. A footnote usually states one length per sentence, but the
#: full stop has to be a sentence ending rather than the point in "7.5 hours" or the
#: dots in "7a.m.-3p.m." - both of which are commoner in these notes than prose is.
_CLAUSE_SPLIT = re.compile(r"[;\n]|\.\s+(?=[A-Z0-9])|\.\s*$")


def parse_footnote(text: str) -> FootnoteTable:
    """Read shift lengths out of a page footnote.

    The pattern is generic - a list of shift tokens, then "is" or "are", then a number
    and the word hours - rather than a fixed sentence, because every facility writes
    this note slightly differently and none of them is going to rewrite it for us.
    """
    if not text:
        return FootnoteTable(text="")
    cleaned = squeeze(normalize_dashes(str(text)))
    by_times: dict[tuple[time, time], float] = {}
    tokens: list[tuple[str, float]] = []

    # One clause at a time, because a footnote states one length per sentence. Within
    # a clause the ranges are collected wherever they fall: real notes put words
    # between them ("Day 7a-3p and evening 3p-11p are 8 hrs"), and a pattern that
    # insists the tokens be adjacent reads half of those as having no footnote at all.
    for clause in _CLAUSE_SPLIT.split(cleaned):
        phrase = _HOURS_PHRASE.search(clause)
        if phrase is None:
            continue
        hours = float(phrase.group(1))
        for match in _RANGE_IN_TEXT.finditer(clause[: phrase.start()]):
            start, _ = _parse_time(match.group(1))
            end, _ = _parse_time(match.group(2))
            if start is None or end is None:
                continue
            by_times[(start, end)] = hours
            tokens.append((match.group(0).strip(), hours))

    return FootnoteTable(by_times=by_times, tokens=tuple(tokens), text=cleaned)


def split_at_midnight(
    start: datetime, end: datetime, hours: float | None = None
) -> list[tuple[date, float]]:
    """Divide a stretch of time into calendar days.

    Reported staffing is counted by calendar day with midnight as the cut, so a night
    shift belongs to two days. When a total is supplied - a footnote length that
    differs from the clock - it is shared out in proportion, so the parts still add up
    to the figure the facility says the shift is worth.
    """
    if end <= start:
        return []
    clock_total = (end - start).total_seconds() / 3600.0
    scale = (hours / clock_total) if hours is not None and clock_total else 1.0

    parts: list[tuple[date, float]] = []
    cursor = start
    while cursor < end:
        next_midnight = datetime.combine(cursor.date() + timedelta(days=1), time.min)
        boundary = min(next_midnight, end)
        span = (boundary - cursor).total_seconds() / 3600.0
        parts.append((cursor.date(), round_hours(span * scale) or 0.0))
        cursor = boundary
    return parts
