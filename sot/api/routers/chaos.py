"""The chaos coverage report.

Served from the file `make chaos` writes, rather than recomputed: running sixty
mutations takes a minute, and the point of the page is to show what the last run
proved, not to prove it again.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from sot.config import settings

router = APIRouter(prefix="/chaos", tags=["chaos"])


@router.get("/coverage")
def coverage() -> dict[str, Any]:
    """The last chaos run's coverage matrix."""
    path = settings().reports_dir / "chaos_coverage.json"
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="no coverage report yet; run `make chaos` to generate one",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"coverage report unreadable: {exc}") from None
