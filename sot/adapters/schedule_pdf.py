"""The weekly schedule PDF adapter.

The hardest input in the system, and the one most likely to differ from what we have
seen. A printed rota has no schema: the table may be ruled or not, the facility may be
in the title or nowhere, the day headings usually have no year, and the shift lengths
live in a sentence at the bottom of the page.

So extraction is attempted three ways, in descending order of confidence, and each
page is handled on its own. A page that cannot be read blocks itself and nothing else,
which matters because a notes page stapled to the back of a rota should not cost us
the rota.

Everything the page says is recorded with its position on the page, so a flag raised
about a shift can point at the rectangle it came from.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sot.adapters.base import AdapterFinding
from sot.canon import round_hours, squeeze
from sot.ids import stable_id
from sot.ingest.contracts import Crosswalk, header_key
from sot.normalize.names import name_key
from sot.normalize.shifts import (
    CellParse,
    FootnoteTable,
    ShiftCategory,
    build_codes,
    normalize_dashes,
    parse_footnote,
    parse_shift_cell,
)

#: Column headings that introduce the two label columns rather than a day.
STAFF_HEADINGS = ("staff", "name", "employee", "staffmember", "staffname", "teammember")
ROLE_HEADINGS = ("role", "title", "position", "job", "jobtitle", "discipline")

_WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "weds": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_WEEKDAY_RE = re.compile(r"\b(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", re.I)
_MONTH_DAY_RE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

#: A page heading has to look like a rota before we trust it as one.
MIN_DAY_COLUMNS = 3

#: Fraction of the page treated as the title area when looking for a facility name.
TITLE_BAND = 0.25

EXTRACTION_LINES = "lines"
EXTRACTION_TEXT = "text"
EXTRACTION_WORDS = "words"


@dataclass
class DayColumn:
    """One day's column in the printed table."""

    index: int
    header: str
    month: int | None = None
    day: int | None = None
    explicit_year: int | None = None
    weekday_claimed: int | None = None
    work_date: date | None = None

    @property
    def weekday_matches(self) -> bool | None:
        if self.work_date is None or self.weekday_claimed is None:
            return None
        return self.work_date.weekday() == self.weekday_claimed


@dataclass
class ExtractedRow:
    """One staff member's row."""

    row_index: int
    staff: str
    role: str
    cells: list[str] = field(default_factory=list)
    bboxes: list[tuple[float, float, float, float] | None] = field(default_factory=list)


@dataclass
class PageResult:
    """One page of the file."""

    number: int
    width: float = 0.0
    height: float = 0.0
    method: str = ""
    facility_code: str | None = None
    facility_source: str = "unknown"
    day_columns: list[DayColumn] = field(default_factory=list)
    rows: list[ExtractedRow] = field(default_factory=list)
    footnote: FootnoteTable = field(default_factory=FootnoteTable)
    readable: bool = False
    text: str = ""
    #: Whatever is printed above the table. Empty means a continuation page.
    heading_text: str = ""


@dataclass
class ScheduleResult:
    """Everything the file turned into."""

    pages: list[PageResult] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    cells: list[dict[str, Any]] = field(default_factory=list)
    findings: list[AdapterFinding] = field(default_factory=list)

    def codes(self) -> list[str]:
        return sorted({finding.code for finding in self.findings})


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------


def parse_day_header(text: str, index: int) -> DayColumn | None:
    """Read a column heading like ``Mon 09/14``, ``9/14 Mon`` or ``09/14/2026``."""
    cleaned = squeeze(normalize_dashes(str(text or "")))
    if not cleaned:
        return None

    weekday_match = _WEEKDAY_RE.search(cleaned)
    weekday = _WEEKDAYS.get(weekday_match.group(1).lower()) if weekday_match else None

    date_match = _MONTH_DAY_RE.search(cleaned)
    if date_match is None:
        # A bare weekday is still a day column; the date comes from its neighbours.
        if weekday is None:
            return None
        return DayColumn(index=index, header=cleaned, weekday_claimed=weekday)

    first, second, year_part = date_match.groups()
    month, day = int(first), int(second)
    if month > 12 and day <= 12:
        # Written day-first. Unusual on a US rota but unambiguous when it happens.
        month, day = day, month
    explicit_year = int(year_part) if year_part and len(year_part) == 4 else None
    if explicit_year is None:
        page_year = _YEAR_RE.search(cleaned)
        explicit_year = int(page_year.group(1)) if page_year else None

    return DayColumn(
        index=index,
        header=cleaned,
        month=month,
        day=day,
        explicit_year=explicit_year,
        weekday_claimed=weekday,
    )


def find_header_row(grid: Sequence[Sequence[str]]) -> int | None:
    """Locate the row that heads the table.

    Recognised by content rather than position: the row with the most columns that
    read as dates. Rotas routinely carry a title, a week label, and a blank line above
    the table, and a printed page may repeat the heading part way down.
    """
    best_index: int | None = None
    best_count = 0
    for index, row in enumerate(grid[:12]):
        count = sum(1 for position, cell in enumerate(row) if parse_day_header(cell, position))
        if count > best_count:
            best_index, best_count = index, count
    return best_index if best_count >= MIN_DAY_COLUMNS else None


def label_column_indexes(header: Sequence[str]) -> tuple[int | None, int | None]:
    """Positions of the staff and role columns."""
    staff_index = role_index = None
    for index, cell in enumerate(header):
        key = header_key(str(cell or ""))
        if staff_index is None and key in STAFF_HEADINGS:
            staff_index = index
        elif role_index is None and key in ROLE_HEADINGS:
            role_index = index
    if staff_index is None and header:
        # Unlabelled first column. A rota always names the person first.
        staff_index = 0
    return (staff_index, role_index)


# ---------------------------------------------------------------------------
# Year inference
# ---------------------------------------------------------------------------


def infer_years(
    columns: Sequence[DayColumn],
    *,
    as_of: date,
    period_hints: Sequence[tuple[date, date]] = (),
) -> tuple[list[DayColumn], str]:
    """Give every day column a year.

    Printed rotas almost never carry one, and getting it wrong moves every shift by a
    year. Three sources, in descending order of authority: a year printed on the page,
    a payroll period that covers these dates, and failing both, the year that puts the
    week nearest the as-of date.

    A week that crosses New Year is handled by walking the columns in order and
    rolling the year forward when the month goes backwards.
    """
    dated = [column for column in columns if column.month and column.day]
    if not dated:
        return (list(columns), "no dates in the headings")

    explicit = next((column.explicit_year for column in dated if column.explicit_year), None)
    if explicit is not None:
        return (_assign(columns, explicit), "a year printed on the page")

    candidate_years = sorted({as_of.year - 1, as_of.year, as_of.year + 1})

    if period_hints:
        for year in candidate_years:
            assigned = _assign(columns, year)
            covered = sum(
                1
                for column in assigned
                if column.work_date
                and any(start <= column.work_date <= end for start, end in period_hints)
            )
            if covered >= max(1, len(dated) // 2):
                return (assigned, "the payroll periods covering these dates")

    best_year = min(
        candidate_years,
        key=lambda year: min(
            abs((candidate.work_date - as_of).days)
            for candidate in _assign(columns, year)
            if candidate.work_date
        ),
    )
    return (_assign(columns, best_year), "the year closest to the as-of date")


def _assign(columns: Sequence[DayColumn], year: int) -> list[DayColumn]:
    """Set the year on every dated column, rolling over at New Year."""
    out: list[DayColumn] = []
    current_year = year
    previous_month: int | None = None
    for column in columns:
        if not column.month or not column.day:
            out.append(column)
            continue
        if previous_month is not None and column.month < previous_month:
            current_year += 1
        previous_month = column.month
        try:
            work_date = date(current_year, column.month, column.day)
        except ValueError:
            work_date = None
        out.append(
            DayColumn(
                index=column.index,
                header=column.header,
                month=column.month,
                day=column.day,
                explicit_year=column.explicit_year,
                weekday_claimed=column.weekday_claimed,
                work_date=work_date,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _extract_tables(
    page: Any,
) -> tuple[list[list[str]], list[list[Any]], str, float, float] | None:
    """Try the ruled grid, then the text layout.

    Returns the cells, their geometry, how it was done, and the y of the table's top
    edge - which is what tells a continuation page from a page with its own title.
    """
    attempts = (
        ({"vertical_strategy": "lines", "horizontal_strategy": "lines"}, EXTRACTION_LINES),
        ({"vertical_strategy": "text", "horizontal_strategy": "text"}, EXTRACTION_TEXT),
    )
    for settings, method in attempts:
        try:
            tables = page.find_tables(settings)
        except Exception:
            continue
        for table in tables:
            try:
                grid = [[squeeze(cell or "") for cell in row] for row in table.extract()]
            except Exception:
                continue
            if find_header_row(grid) is None:
                continue
            geometry = [list(row.cells) for row in table.rows]
            return (grid, geometry, method, float(table.bbox[1]), float(table.bbox[3]))
    return None


def _cluster_words(
    page: Any,
) -> tuple[list[list[str]], list[list[Any]], str, float, float] | None:
    """Last resort: rebuild the table from where the words sit on the page.

    Used when the page has text but no structure a table finder can see - no rules,
    and columns separated by spacing a layout algorithm does not recognise. Rows come
    from vertical position; columns come from the x-positions of the heading words,
    which is the only reliable anchor on a page with no lines.
    """
    try:
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    except Exception:
        return None
    if not words:
        return None

    lines: dict[int, list[dict]] = {}
    for word in words:
        key = round(float(word["top"]) / 3.0)
        lines.setdefault(key, []).append(word)

    ordered = [sorted(group, key=lambda w: w["x0"]) for _, group in sorted(lines.items())]

    header_line = None
    for group in ordered:
        count = sum(1 for word in group if parse_day_header(word["text"], 0))
        if count >= MIN_DAY_COLUMNS:
            header_line = group
            break
    if header_line is None:
        return None

    # Column boundaries sit midway between the left edges of adjacent headings.
    starts = [float(word["x0"]) for word in header_line]
    boundaries = [(starts[index] + starts[index + 1]) / 2 for index in range(len(starts) - 1)]

    def column_of(x: float) -> int:
        for index, boundary in enumerate(boundaries):
            if x < boundary:
                return index
        return len(boundaries)

    grid: list[list[str]] = []
    geometry: list[list[Any]] = []
    width = len(header_line)
    for group in ordered:
        cells = [""] * width
        boxes: list[Any] = [None] * width
        for word in group:
            index = min(column_of(float(word["x0"])), width - 1)
            cells[index] = f"{cells[index]} {word['text']}".strip()
            box = (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))
            existing = boxes[index]
            boxes[index] = (
                box
                if existing is None
                else (
                    min(existing[0], box[0]),
                    min(existing[1], box[1]),
                    max(existing[2], box[2]),
                    max(existing[3], box[3]),
                )
            )
        if any(cells):
            grid.append(cells)
            geometry.append(boxes)

    if find_header_row(grid) is None:
        return None
    top = min((float(word["top"]) for word in header_line), default=0.0)
    bottom = max(
        (float(box[3]) for row in geometry for box in row if box), default=float(page.height)
    )
    return (grid, geometry, EXTRACTION_WORDS, top, bottom)


def _merge_wrapped_rows(
    grid: list[list[str]], geometry: list[list[Any]], staff_index: int
) -> tuple[list[list[str]], list[list[Any]]]:
    """Fold continuation lines into the row above.

    A long name or a doubled shift wraps onto a second printed line, which arrives as a
    row with an empty staff cell. Left alone it becomes a phantom staff member with a
    few stray shifts.
    """
    merged_grid: list[list[str]] = []
    merged_geometry: list[list[Any]] = []
    for row, boxes in zip(grid, geometry, strict=False):
        has_staff = staff_index < len(row) and bool(squeeze(row[staff_index]))
        if not has_staff and merged_grid and any(squeeze(cell) for cell in row):
            target = merged_grid[-1]
            for index, cell in enumerate(row):
                if index < len(target) and squeeze(cell):
                    target[index] = squeeze(f"{target[index]} {cell}")
            continue
        merged_grid.append(list(row))
        merged_geometry.append(list(boxes))
    return (merged_grid, merged_geometry)


def _text_above(page: Any, table_top: float) -> str:
    """Whatever is printed above the table.

    A page with a title that we simply do not recognise is a different thing from a
    page with no title at all. The first needs its facility inferring and saying so;
    the second is a table that spilled over and should quietly continue the page
    before it.
    """
    if table_top <= 1:
        return ""
    try:
        band = page.crop((0, 0, page.width, max(table_top - 1, 1)))
        return (band.extract_text() or "").strip()
    except Exception:
        return ""


def _text_below(page: Any, table_bottom: float) -> str:
    """Whatever is printed below the table.

    The footnote is read from here rather than from the whole page, because the page
    also contains every shift in the table - and a pattern looking for shift tokens
    before the words "are 8 hours" will happily sweep the rota itself into the
    footnote and then price every shift wrongly.
    """
    try:
        if table_bottom >= page.height - 1:
            return ""
        band = page.crop((0, min(table_bottom + 1, page.height - 1), page.width, page.height))
        return (band.extract_text() or "").strip()
    except Exception:
        return ""


def _find_facility(
    text: str, height: float, page: Any, crosswalk: Crosswalk | None
) -> tuple[str | None, str]:
    """Match the page against the facility crosswalk, title area first."""
    if crosswalk is None:
        return (None, "unknown")

    aliases: list[tuple[str, str]] = []
    for entry in crosswalk.entries:
        for raw in (entry.name, *entry.aliases, entry.code):
            if raw:
                aliases.append((raw, entry.code))
    # Longest alias first, so a full site name wins over a bare one it contains.
    aliases.sort(key=lambda item: -len(item[0]))

    title_text = ""
    try:
        band = page.crop((0, 0, page.width, max(height * TITLE_BAND, 1)))
        title_text = band.extract_text() or ""
    except Exception:
        title_text = ""

    for haystack, source in ((title_text, "title"), (text, "body")):
        folded = header_key(haystack)
        for alias, code in aliases:
            key = header_key(alias)
            if key and key in folded:
                return (code, source)
    return (None, "unknown")


def _infer_facility_from_staff(
    rows: Iterable[ExtractedRow], home_facility_by_key: Mapping[str, str]
) -> str | None:
    """Fall back to where the people on this page usually work."""
    if not home_facility_by_key:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        code = home_facility_by_key.get(name_key(row.staff))
        if code:
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None  # a tie is not a majority
    return ranked[0][0]


#: How much to trust each extraction route.
CONFIDENCE = {EXTRACTION_LINES: 1.0, EXTRACTION_TEXT: 0.9, EXTRACTION_WORDS: 0.7}


def _modal_hours(parses: Iterable[CellParse], footnote: FootnoteTable) -> float:
    """How long a day off is worth for this person.

    A rota cell saying PTO does not say how many hours. The person's own usual shift
    that week is the best available answer; the facility's commonest shift is the next
    best. Both are assumptions, and both are recorded on the segment.
    """
    lengths = [
        segment.hours
        for parse in parses
        if parse.category is ShiftCategory.WORK
        for segment in parse.segments
    ]
    if lengths:
        return max(sorted(set(lengths)), key=lengths.count)
    if footnote.by_times:
        values = list(footnote.by_times.values())
        return max(sorted(set(values)), key=values.count)
    return 8.0


def _page_findings_for_cell(
    parse: CellParse,
    quality_code: str | None,
    page: PageResult,
    row: ExtractedRow,
    column: DayColumn,
    bbox: tuple[float, float, float, float] | None,
    note: str,
) -> list[AdapterFinding]:
    """Everything worth reporting about one cell."""
    findings: list[AdapterFinding] = []
    if quality_code == "SHIFT_AMBIGUOUS_ASSUMED":
        findings.append(
            AdapterFinding(
                "SHIFT_AMBIGUOUS_ASSUMED",
                {"count": 1, "example": parse.raw, "resolved": note, "page": page.number},
                page=page.number,
                row_index=row.row_index,
                column=column.header,
                raw_value=parse.raw,
                bbox=bbox,
            )
        )
    if parse.category is ShiftCategory.PTO:
        findings.append(
            AdapterFinding(
                "PTO_ON_SCHEDULE",
                {"count": 1, "codes": parse.code, "page": page.number},
                page=page.number,
                row_index=row.row_index,
                column=column.header,
                raw_value=parse.raw,
                bbox=bbox,
            )
        )
    for segment in parse.segments:
        if segment.hours_source == "clock" and page.footnote:
            findings.append(
                AdapterFinding(
                    "SHIFT_NOT_IN_FOOTNOTE",
                    {"count": 1, "example": segment.token, "page": page.number},
                    page=page.number,
                    row_index=row.row_index,
                    column=column.header,
                    raw_value=parse.raw,
                    bbox=bbox,
                )
            )
        elif segment.hours_source == "footnote" and segment.hours != segment.clock_hours:
            findings.append(
                AdapterFinding(
                    "FOOTNOTE_CLOCK_MISMATCH",
                    {
                        "token": segment.token,
                        "footnote_hours": segment.hours,
                        "clock_hours": segment.clock_hours,
                        "page": page.number,
                    },
                    page=page.number,
                    column=column.header,
                    raw_value=parse.raw,
                    bbox=bbox,
                    key_parts=(str(page.number), segment.token),
                )
            )
    return findings


def extract_schedule(
    data: bytes,
    *,
    file_id: str,
    source_type: str = "schedule",
    as_of: date,
    facilities: Crosswalk | None = None,
    roles: Crosswalk | None = None,
    shift_codes: Mapping[str, Iterable[str]] | None = None,
    period_hints: Sequence[tuple[date, date]] = (),
    home_facility_by_key: Mapping[str, str] | None = None,
) -> ScheduleResult:
    """Read a printed weekly rota into shift segments.

    Each page stands alone: one that cannot be read blocks itself and leaves the rest
    of the file intact, which is what lets a notes page stapled to the back of a rota
    be harmless.
    """
    import pdfplumber

    result = ScheduleResult()
    codes = build_codes(shift_codes)
    home_facility_by_key = home_facility_by_key or {}
    period_end = max((end for _, end in period_hints), default=None)

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, raw_page in enumerate(pdf.pages, start=1):
            page = _read_page(raw_page, number, facilities, result)
            result.pages.append(page)

    _resolve_facilities(result, home_facility_by_key)

    for page in result.pages:
        if not page.readable:
            continue
        page.day_columns, basis = infer_years(
            page.day_columns, as_of=as_of, period_hints=period_hints
        )
        _report_weekday_mismatches(page, basis, result)
        _emit_page(page, result, file_id, source_type, roles, codes, period_end)

    _report_cross_page(result)
    return result


def _read_page(
    raw_page: Any, number: int, facilities: Crosswalk | None, result: ScheduleResult
) -> PageResult:
    """Extract one page's structure, or record why it could not be read."""
    page = PageResult(number=number, width=float(raw_page.width), height=float(raw_page.height))
    try:
        page.text = raw_page.extract_text() or ""
    except Exception:
        page.text = ""

    if not page.text.strip():
        # No text layer. OCR would go here when it is available; without it the page
        # blocks itself and the rest of the file carries on.
        result.findings.append(
            AdapterFinding(
                "PDF_NO_TEXT_LAYER",
                {"page": number, "ocr_used": False, "ocr_note": ""},
                page=number,
                key_parts=(str(number),),
            )
        )
        return page

    extracted = _extract_tables(raw_page) or _cluster_words(raw_page)
    if extracted is None:
        result.findings.append(
            AdapterFinding(
                "PDF_TABLE_NOT_FOUND", {"page": number}, page=number, key_parts=(str(number),)
            )
        )
        return page

    grid, geometry, method, table_top, table_bottom = extracted
    page.method = method
    page.heading_text = _text_above(raw_page, table_top)
    header_index = find_header_row(grid)
    if header_index is None:
        result.findings.append(
            AdapterFinding(
                "PDF_TABLE_NOT_FOUND", {"page": number}, page=number, key_parts=(str(number),)
            )
        )
        return page

    header = grid[header_index]
    page.day_columns = [
        column
        for column in (parse_day_header(cell, index) for index, cell in enumerate(header))
        if column is not None
    ]
    staff_index, role_index = label_column_indexes(header)
    if staff_index is None:
        result.findings.append(
            AdapterFinding(
                "PDF_TABLE_NOT_FOUND", {"page": number}, page=number, key_parts=(str(number),)
            )
        )
        return page

    body = grid[header_index + 1 :]
    body_geometry = geometry[header_index + 1 :]
    body, body_geometry = _merge_wrapped_rows(body, body_geometry, staff_index)

    for offset, (row, boxes) in enumerate(zip(body, body_geometry, strict=False)):
        staff = squeeze(row[staff_index]) if staff_index < len(row) else ""
        if not staff:
            continue
        role = squeeze(row[role_index]) if role_index is not None and role_index < len(row) else ""
        page.rows.append(
            ExtractedRow(
                row_index=header_index + 2 + offset,
                staff=staff,
                role=role,
                cells=[squeeze(cell) for cell in row],
                bboxes=list(boxes),
            )
        )

    page.footnote = parse_footnote(_text_below(raw_page, table_bottom) or page.text)
    if not page.footnote:
        result.findings.append(
            AdapterFinding(
                "PDF_FOOTNOTE_MISSING", {"page": number}, page=number, key_parts=(str(number),)
            )
        )

    page.facility_code, page.facility_source = _find_facility(
        page.text, page.height, raw_page, facilities
    )
    page.readable = True
    return page


def _resolve_facilities(result: ScheduleResult, home_facility_by_key: Mapping[str, str]) -> None:
    """Give every readable page a facility, or say why it has none.

    Three routes, in order. A page with a table whose columns match the one before it
    and no facility of its own is a continuation of that page - a table that spilled
    over - and inherits silently. Otherwise the staff listed on the page usually give
    it away. A page with neither can only block itself.
    """
    previous: PageResult | None = None
    for page in result.pages:
        if not page.readable:
            continue
        if page.facility_code is None:
            headers = [column.header for column in page.day_columns]
            previous_headers = (
                [column.header for column in previous.day_columns] if previous else []
            )
            is_continuation = (
                not page.heading_text
                and previous is not None
                and previous.facility_code is not None
                and headers == previous_headers
            )
            if is_continuation:
                page.facility_code = previous.facility_code
                page.facility_source = "carried"
                result.findings.append(
                    AdapterFinding(
                        "PDF_FACILITY_UNKNOWN",
                        {
                            "page": page.number,
                            "carried": True,
                            "inferred_facility": previous.facility_code,
                            "resolution": (
                                f"It has no heading of its own, so it continues page "
                                f"{previous.number} at {previous.facility_code}."
                            ),
                        },
                        page=page.number,
                        key_parts=(str(page.number),),
                    )
                )
            else:
                inferred = _infer_facility_from_staff(page.rows, home_facility_by_key)
                page.facility_code = inferred
                page.facility_source = "inferred" if inferred else "unknown"
                result.findings.append(
                    AdapterFinding(
                        "PDF_FACILITY_UNKNOWN",
                        {
                            "page": page.number,
                            "inferred_facility": inferred,
                            "resolution": (
                                f"Inferred as {inferred} from the staff listed on it."
                                if inferred
                                else "It could not be inferred from the staff either, so "
                                "nothing on this page has been used."
                            ),
                        },
                        page=page.number,
                        key_parts=(str(page.number),),
                    )
                )
                if inferred is None:
                    page.readable = False
        previous = page


def _report_weekday_mismatches(page: PageResult, basis: str, result: ScheduleResult) -> None:
    """A heading whose weekday does not match its date. The date is trusted."""
    for column in page.day_columns:
        if column.weekday_matches is False and column.work_date:
            result.findings.append(
                AdapterFinding(
                    "WEEKDAY_DATE_MISMATCH",
                    {
                        "facility": page.facility_code or f"page {page.number}",
                        "header": column.header,
                        "parsed_date": column.work_date.isoformat(),
                        "actual_weekday": _WEEKDAY_NAMES[column.work_date.weekday()],
                        "year_basis": basis,
                    },
                    page=page.number,
                    column=column.header,
                    key_parts=(str(page.number), column.header),
                )
            )


def _emit_page(
    page: PageResult,
    result: ScheduleResult,
    file_id: str,
    source_type: str,
    roles: Crosswalk | None,
    codes: Mapping[str, frozenset[str]],
    period_end: date | None,
) -> None:
    """Turn one page's cells into stored cells and shift segments.

    Two rows for the same person on one page is a finding, but identity resolution
    raises it rather than this does: by then a shortened given name and its full form
    are known to be one person, which comparing the printed text cannot see.
    """
    for row in page.rows:
        role_code = roles.resolve(row.role) if roles and row.role else None

        parses: list[tuple[DayColumn, CellParse | None, str | None, str, Any]] = []
        for column in page.day_columns:
            text = row.cells[column.index] if column.index < len(row.cells) else ""
            bbox = row.bboxes[column.index] if column.index < len(row.bboxes) else None
            result.cells.append(
                {
                    "file_id": file_id,
                    "page": page.number,
                    "row_index": row.row_index,
                    "col_index": column.index,
                    "column_header": column.header,
                    "text": text,
                    "x0": bbox[0] if bbox else None,
                    "top": bbox[1] if bbox else None,
                    "x1": bbox[2] if bbox else None,
                    "bottom": bbox[3] if bbox else None,
                    "page_width": page.width,
                    "page_height": page.height,
                    "extraction_method": page.method,
                    "confidence": CONFIDENCE.get(page.method, 0.5),
                }
            )
            parsed = parse_shift_cell(text, footnote=page.footnote, codes=codes)
            if parsed.value is None:
                result.findings.append(
                    AdapterFinding(
                        "SHIFT_UNPARSEABLE",
                        {
                            "display_name": row.staff,
                            "column_header": column.header,
                            "page": page.number,
                            "raw_value": text,
                        },
                        page=page.number,
                        row_index=row.row_index,
                        column=column.header,
                        raw_value=text,
                        bbox=bbox,
                        key_parts=(str(page.number), str(row.row_index), str(column.index)),
                    )
                )
                parses.append((column, None, parsed.code, parsed.note, bbox))
                continue
            parses.append((column, parsed.value, parsed.code, parsed.note, bbox))

        pto_hours = _modal_hours([p for _, p, _, _, _ in parses if p], page.footnote)

        for column, parse, quality_code, note, bbox in parses:
            if parse is None or column.work_date is None:
                continue
            result.findings.extend(
                _page_findings_for_cell(parse, quality_code, page, row, column, bbox, note)
            )
            if parse.category is ShiftCategory.OFF:
                continue
            _emit_segments(
                result,
                page,
                row,
                column,
                parse,
                bbox,
                file_id,
                source_type,
                role_code,
                pto_hours,
                period_end,
            )


def _emit_segments(
    result: ScheduleResult,
    page: PageResult,
    row: ExtractedRow,
    column: DayColumn,
    parse: CellParse,
    bbox: Any,
    file_id: str,
    source_type: str,
    role_code: str | None,
    pto_hours: float,
    period_end: date | None,
) -> None:
    """Record the time a single cell represents."""
    work_date = column.work_date
    assert work_date is not None

    if not parse.segments:
        # An absence code with no times: PTO, training or on call for the whole day.
        hours = pto_hours if parse.category is ShiftCategory.PTO else 0.0
        result.segments.append(
            _segment_row(
                file_id,
                source_type,
                page,
                row,
                column,
                parse,
                bbox,
                work_date=work_date,
                start=None,
                end=None,
                hours=hours,
                category=parse.category,
                hours_source="assumed",
                note=(
                    f"{parse.code} with no times; {hours} hours assumed from the "
                    "person's usual shift"
                    if hours
                    else f"{parse.code} recorded with no hours"
                ),
                sequence=0,
                role_code=role_code,
            )
        )
        return

    for sequence, segment in enumerate(parse.segments):
        start_ts, end_ts = segment.timestamps(work_date)
        note = ""
        if period_end is not None and end_ts.date() > period_end:
            note = f"runs to {end_ts.isoformat(sep=' ')}, past the end of the period"
            result.findings.append(
                AdapterFinding(
                    "SHIFT_SPANS_PERIOD",
                    {
                        "count": 1,
                        "display_name": row.staff,
                        "token": segment.token,
                        "work_date": work_date.isoformat(),
                        "end_ts": end_ts.isoformat(sep=" "),
                        "page": page.number,
                    },
                    page=page.number,
                    row_index=row.row_index,
                    column=column.header,
                    raw_value=parse.raw,
                    bbox=bbox,
                )
            )
        result.segments.append(
            _segment_row(
                file_id,
                source_type,
                page,
                row,
                column,
                parse,
                bbox,
                work_date=work_date,
                start=start_ts,
                end=end_ts,
                hours=segment.hours,
                category=parse.category,
                hours_source=segment.hours_source,
                note=note,
                sequence=sequence,
                role_code=role_code,
                token=segment.token,
            )
        )


def _segment_row(
    file_id: str,
    source_type: str,
    page: PageResult,
    row: ExtractedRow,
    column: DayColumn,
    parse: CellParse,
    bbox: Any,
    *,
    work_date: date,
    start: datetime | None,
    end: datetime | None,
    hours: float,
    category: ShiftCategory,
    hours_source: str,
    note: str,
    sequence: int,
    role_code: str | None,
    token: str = "",
) -> dict[str, Any]:
    return {
        "segment_id": stable_id(
            "SG",
            {
                "file": file_id,
                "page": page.number,
                "row": row.row_index,
                "col": column.index,
                "seq": sequence,
            },
        ),
        "file_id": file_id,
        "source_type": source_type,
        "person_ref": row.staff,
        "facility_code": page.facility_code,
        "role_code": role_code,
        "work_date": work_date,
        "start_ts": start,
        "end_ts": end,
        "hours": round_hours(hours),
        "category": str(category),
        "hours_source": hours_source,
        "page": page.number,
        "row_index": row.row_index,
        "col_index": column.index,
        "column_header": column.header,
        "raw_text": parse.raw or token,
        "confidence": CONFIDENCE.get(page.method, 0.5),
        "note": note or None,
    }


def _report_cross_page(result: ScheduleResult) -> None:
    """Findings that only become visible once every page is read."""
    pages_by_person: dict[str, set[str]] = {}
    display_by_key: dict[str, str] = {}
    for page in result.pages:
        if not page.readable or not page.facility_code:
            continue
        for row in page.rows:
            key = name_key(row.staff)
            pages_by_person.setdefault(key, set()).add(page.facility_code)
            display_by_key.setdefault(key, row.staff)

    for key, facilities in sorted(pages_by_person.items()):
        if len(facilities) > 1:
            result.findings.append(
                AdapterFinding(
                    "PERSON_ON_MULTIPLE_PAGES",
                    {
                        "display_name": display_by_key[key],
                        "page_count": len(facilities),
                        "facilities": ", ".join(sorted(facilities)),
                    },
                    key_parts=(key,),
                )
            )
