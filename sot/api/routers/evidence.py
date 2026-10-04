"""Evidence: the actual cell, or the actual rectangle on the page.

A flag is only worth as much as the thing it points at. These endpoints serve the
source row and the rendered page so the viewer can highlight exactly what caused a
finding, rather than asking somebody to go and look it up.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from sot.api import deps
from sot.config import settings

router = APIRouter(prefix="/evidence", tags=["evidence"])

#: Pixels per inch for the rendered page. High enough to read a shift cell on a
#: projector, low enough that a page is not a megabyte.
RENDER_DPI = 144


@router.get("/file/{file_id}/row/{row_index}")
def file_row(file_id: str, row_index: int, run_id: str | None = None) -> dict[str, Any]:
    """One row of one file, raw and normalized, with its neighbours for context."""
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    row = database.query_one(
        "SELECT * FROM raw_rows WHERE run_id = ? AND file_id = ? AND row_index = ?",
        [resolved, file_id, row_index],
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"no row {row_index} in {file_id}")

    meta = database.query_one(
        "SELECT original_name, detected_source, media_kind FROM files WHERE file_id = ?",
        [file_id],
    )
    neighbours = database.query(
        "SELECT row_index, raw_json, status FROM raw_rows WHERE run_id = ? AND file_id = ? "
        "AND row_index BETWEEN ? AND ? ORDER BY row_index",
        [resolved, file_id, row_index - 2, row_index + 2],
    )
    return {
        "run_id": resolved,
        "file_id": file_id,
        "file": meta["original_name"] if meta else "",
        "source_type": meta["detected_source"] if meta else "",
        "row_index": row_index,
        "status": row["status"],
        "note": row["note"],
        "raw": json.loads(row["raw_json"] or "{}"),
        "normalized": json.loads(row["norm_json"] or "{}"),
        "context": [
            {
                "row_index": item["row_index"],
                "status": item["status"],
                "raw": json.loads(item["raw_json"] or "{}"),
            }
            for item in neighbours
        ],
    }


@router.get("/pdf/{file_id}/page/{page}.png")
def pdf_page(file_id: str, page: int) -> FileResponse:
    """A page of a schedule, rendered once and cached on disk.

    Rendered lazily rather than during ingestion: most pages are never looked at, and
    a run should not pay for images nobody opens.
    """
    database = deps.db()
    record = database.query_one(
        "SELECT stored_path, media_kind FROM files WHERE file_id = ?", [file_id]
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"no file {file_id}")
    if record["media_kind"] != "pdf":
        raise HTTPException(status_code=400, detail=f"{file_id} is not a PDF")

    target = settings().pages_dir / file_id / f"{page}.png"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            _render(record["stored_path"], page, target)
        except IndexError:
            raise HTTPException(status_code=404, detail=f"no page {page}") from None
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"could not render: {exc}") from None
    return FileResponse(target, media_type="image/png")


def _render(source: str, page: int, destination: Any) -> None:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(source)
    try:
        if page < 1 or page > len(document):
            raise IndexError(page)
        rendered = document[page - 1].render(scale=RENDER_DPI / 72.0)
        rendered.to_pil().save(destination, format="PNG")
    finally:
        document.close()


@router.get("/pdf/{file_id}/page/{page}/cells")
def pdf_cells(file_id: str, page: int, run_id: str | None = None) -> dict[str, Any]:
    """Every cell on a page with its rectangle, so the viewer can draw boxes.

    Positions are in PDF points with the render scale alongside, so the client maps
    to pixels without having to re-derive anything.
    """
    database = deps.db()
    resolved = deps.resolve_run_id(database, run_id)
    cells = database.query(
        "SELECT * FROM pdf_cells WHERE run_id = ? AND file_id = ? AND page = ? "
        "ORDER BY row_index, col_index",
        [resolved, file_id, page],
    )
    if not cells:
        raise HTTPException(status_code=404, detail=f"no cells for page {page}")
    first = cells[0]
    return {
        "run_id": resolved,
        "file_id": file_id,
        "page": page,
        "page_width": first["page_width"],
        "page_height": first["page_height"],
        "render_scale": RENDER_DPI / 72.0,
        "extraction_method": first["extraction_method"],
        "cells": [
            {
                "row": cell["row_index"],
                "col": cell["col_index"],
                "column_header": cell["column_header"],
                "text": cell["text"],
                "bbox": [cell["x0"], cell["top"], cell["x1"], cell["bottom"]],
                "confidence": cell["confidence"],
            }
            for cell in cells
        ],
    }
