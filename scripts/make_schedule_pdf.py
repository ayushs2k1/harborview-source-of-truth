"""Parametric weekly-schedule PDF generator.

The schedule arrives as a printed page, which makes it the least predictable input in
the system and the most likely thing to break against the judges' real file. So this
generator is deliberately configurable rather than fixed: the chaos deck mutates the
dash character, the footnote, the header wording, the rows per page, the grid lines,
and whether the page has a text layer at all, and the adapter has to cope with each.

Output is byte-reproducible: reportlab's ``invariant`` mode fixes the embedded creation
date and document id, so regenerating the fixtures never shows up as a diff.

Usable as a library (``write_schedule_pdf``) or from the command line for a quick look.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas as pdfcanvas

#: Dash characters a real export might use between shift times. The adapter normalizes
#: all of them; the generator can emit any one of them.
DASHES = {
    "hyphen": "-",
    "en": "\u2013",
    "em": "\u2014",
    "minus": "\u2212",
    "non_breaking": "\u2011",
}


@dataclass(frozen=True)
class ScheduleRow:
    """One staff member's week."""

    staff: str
    role: str
    cells: tuple[str, ...]


@dataclass(frozen=True)
class SchedulePage:
    """One printed page.

    ``facility_label`` may be empty, which is how the fixture exercises facility
    inference from the staff listed on the page. ``body_text`` with no rows produces a
    prose page, which is how a notes page gets into a schedule file.
    """

    facility_label: str
    week_label: str
    day_headers: tuple[str, ...]
    rows: tuple[ScheduleRow, ...] = ()
    footnote: str | None = None
    body_text: str | None = None


@dataclass(frozen=True)
class PdfOptions:
    """Everything the chaos deck is allowed to vary."""

    dash: str = "-"
    rows_per_page: int | None = None
    draw_grid: bool = True
    staff_header: str = "Staff"
    role_header: str = "Role"
    title_suffix: str = "Weekly Staff Schedule"
    font_name: str = "Helvetica"
    bold_font_name: str = "Helvetica-Bold"
    font_size: float = 9.0
    title_size: float = 13.0
    page_size: tuple[float, float] = field(default_factory=lambda: landscape(letter))
    margin: float = 36.0
    row_height: float = 18.0
    staff_col_width: float = 120.0
    role_col_width: float = 46.0


def _apply_dash(text: str, dash: str) -> str:
    """Swap the plain hyphen in shift tokens for the configured dash."""
    return text.replace("-", dash) if dash != "-" else text


def _paginate(page: SchedulePage, rows_per_page: int | None) -> list[SchedulePage]:
    """Split one logical page across printed pages.

    Continuation pages keep the table header but drop the facility title, which is
    exactly the real-world case the adapter has to recognise: a page with a table and
    no facility continues the previous page's facility.
    """
    if rows_per_page is None or len(page.rows) <= rows_per_page:
        return [page]
    chunks: list[SchedulePage] = []
    for start in range(0, len(page.rows), rows_per_page):
        chunk = page.rows[start : start + rows_per_page]
        first = start == 0
        chunks.append(
            replace(
                page,
                rows=chunk,
                facility_label=page.facility_label if first else "",
                week_label=page.week_label if first else "",
                # The footnote is printed once, on the last page of the table.
                footnote=page.footnote if start + rows_per_page >= len(page.rows) else None,
            )
        )
    return chunks


def _column_x_positions(page: SchedulePage, options: PdfOptions) -> list[float]:
    """Left edge of every column, plus the right edge of the last one."""
    width = options.page_size[0]
    usable = width - 2 * options.margin
    day_total = usable - options.staff_col_width - options.role_col_width
    day_width = day_total / max(len(page.day_headers), 1)
    x = options.margin
    positions = [x]
    x += options.staff_col_width
    positions.append(x)
    x += options.role_col_width
    positions.append(x)
    for _ in page.day_headers:
        x += day_width
        positions.append(x)
    return positions


def _draw_page(c: pdfcanvas.Canvas, page: SchedulePage, options: PdfOptions) -> None:
    """Render one printed page onto the canvas."""
    page_width, page_height = options.page_size
    y = page_height - options.margin

    if page.facility_label:
        c.setFont(options.bold_font_name, options.title_size)
        c.drawString(options.margin, y - options.title_size, page.facility_label)
        y -= options.title_size + 6
    if page.week_label:
        c.setFont(options.font_name, options.font_size + 1)
        c.drawString(options.margin, y - options.font_size, page.week_label)
        y -= options.font_size + 10
    if page.facility_label or page.week_label:
        c.setFont(options.font_name, options.font_size)
        c.drawRightString(
            page_width - options.margin,
            y + options.font_size,
            options.title_suffix,
        )
        y -= 6

    if page.body_text is not None and not page.rows:
        c.setFont(options.font_name, options.font_size + 1)
        for line in page.body_text.splitlines():
            y -= options.font_size + 4
            c.drawString(options.margin, y, line)
        return

    columns = _column_x_positions(page, options)
    headers = [options.staff_header, options.role_header, *page.day_headers]
    table_top = y

    c.setFont(options.bold_font_name, options.font_size)
    y -= options.row_height
    for index, header in enumerate(headers):
        c.drawString(columns[index] + 3, y + 5, header)

    c.setFont(options.font_name, options.font_size)
    for row in page.rows:
        y -= options.row_height
        values = [row.staff, row.role, *(_apply_dash(cell, options.dash) for cell in row.cells)]
        for index, value in enumerate(values):
            if index < len(columns) - 1:
                c.drawString(columns[index] + 3, y + 5, value)

    table_bottom = y
    if options.draw_grid:
        c.setStrokeColor(colors.HexColor("#999999"))
        c.setLineWidth(0.4)
        for x in columns:
            c.line(x, table_top, x, table_bottom)
        line_y = table_top
        for _ in range(len(page.rows) + 2):
            c.line(columns[0], line_y, columns[-1], line_y)
            line_y -= options.row_height
            if line_y < table_bottom - 0.01:
                break
        c.line(columns[0], table_bottom, columns[-1], table_bottom)

    if page.footnote:
        c.setFont(options.font_name, options.font_size)
        c.drawString(options.margin, table_bottom - options.row_height, page.footnote)


def write_schedule_pdf(
    path: str | Path,
    pages: list[SchedulePage],
    options: PdfOptions | None = None,
) -> Path:
    """Write ``pages`` to a PDF at ``path`` and return the path."""
    options = options or PdfOptions()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # invariant=1 fixes the creation date and document id, so identical input gives
    # identical bytes and regenerating fixtures is never a spurious diff.
    c = pdfcanvas.Canvas(str(destination), pagesize=options.page_size, invariant=1)
    c.setTitle(options.title_suffix)
    c.setAuthor("sample generator")
    c.setSubject("weekly staff schedule")

    printed = [p for page in pages for p in _paginate(page, options.rows_per_page)]
    for page in printed:
        _draw_page(c, page, options)
        c.showPage()
    c.save()
    return destination


def rasterize_pdf(source: str | Path, destination: str | Path, dpi: int = 150) -> Path:
    """Re-render a PDF as page images with no text layer.

    This is how the scanned fixture is produced. The result is what a care home
    actually emails you: a photocopy of a printout, with nothing selectable on it.
    """
    import pypdfium2 as pdfium
    from reportlab.lib.utils import ImageReader

    source_path, dest_path = Path(source), Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(source_path))
    try:
        first = document[0]
        size = (first.get_width(), first.get_height())
        c = pdfcanvas.Canvas(str(dest_path), pagesize=size, invariant=1)
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=dpi / 72.0)
            image = bitmap.to_pil()
            c.setPageSize((page.get_width(), page.get_height()))
            c.drawImage(ImageReader(image), 0, 0, width=page.get_width(), height=page.get_height())
            c.showPage()
        c.save()
    finally:
        document.close()
    return dest_path


def _demo_pages() -> list[SchedulePage]:
    """A tiny two-row page, for eyeballing the layout from the command line."""
    days = ("Mon 09/14", "Tue 09/15", "Wed 09/16")
    return [
        SchedulePage(
            facility_label="Example Facility",
            week_label="Week of Mon 09/14",
            day_headers=days,
            rows=(
                ScheduleRow("Example Person", "RN", ("7a-3p", "7a-3p", "OFF")),
                ScheduleRow("Another Person", "CNA", ("3p-11p", "OFF", "3p-11p")),
            ),
            footnote="Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours.",
        )
    ]


def main() -> int:
    """Render a schedule PDF from a JSON page description, or a built-in demo."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="path to write the PDF to")
    parser.add_argument("--pages-json", help="file holding a JSON list of pages")
    parser.add_argument("--dash", choices=sorted(DASHES), default="hyphen")
    parser.add_argument("--rows-per-page", type=int, default=None)
    parser.add_argument("--no-grid", action="store_true")
    parser.add_argument("--no-footnote", action="store_true")
    parser.add_argument("--scan", action="store_true", help="also write an image-only copy")
    args = parser.parse_args()

    if args.pages_json:
        raw = json.loads(Path(args.pages_json).read_text(encoding="utf-8"))
        pages = [
            SchedulePage(
                facility_label=item.get("facility_label", ""),
                week_label=item.get("week_label", ""),
                day_headers=tuple(item.get("day_headers", ())),
                rows=tuple(ScheduleRow(**row) for row in item.get("rows", ())),
                footnote=item.get("footnote"),
                body_text=item.get("body_text"),
            )
            for item in raw
        ]
    else:
        pages = _demo_pages()

    if args.no_footnote:
        pages = [replace(page, footnote=None) for page in pages]

    options = PdfOptions(
        dash=DASHES[args.dash],
        rows_per_page=args.rows_per_page,
        draw_grid=not args.no_grid,
    )
    written = write_schedule_pdf(args.output, pages, options)
    print(f"wrote {written}")
    if args.scan:
        scanned = rasterize_pdf(written, written.with_name(written.stem + "_scan.pdf"))
        print(f"wrote {scanned}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
