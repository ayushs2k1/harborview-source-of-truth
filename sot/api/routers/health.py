"""Health and pack discovery."""

from __future__ import annotations

from datetime import date
from typing import Any

import yaml
from fastapi import APIRouter

from sot.config import ENGINE_VERSION, settings
from sot.store.db import get_db

router = APIRouter(tags=["meta"])


def _discover_packs() -> list[dict[str, Any]]:
    """Every directory under ``packs/`` holding a readable ``pack.yaml``.

    A pack with broken YAML is reported with its error rather than omitted: a pack that
    silently disappears from the switcher is far harder to debug than one that says why
    it will not load.
    """
    packs_dir = settings().packs_dir
    if not packs_dir.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for candidate in sorted(packs_dir.iterdir()):
        manifest = candidate / "pack.yaml"
        if not manifest.is_file():
            continue
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            found.append(
                {
                    "id": candidate.name,
                    "name": data.get("name", candidate.name),
                    "version": str(data.get("version", "")),
                    "description": data.get("description", ""),
                    "ok": True,
                }
            )
        except yaml.YAMLError as exc:
            found.append(
                {"id": candidate.name, "name": candidate.name, "ok": False, "error": str(exc)}
            )
    return found


@router.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus enough detail to diagnose a bad install at a glance."""
    database: dict[str, Any]
    try:
        db = get_db()
        database = {"path": str(db.path), "ok": True, "tables": len(db.table_names())}
    except Exception as exc:  # pragma: no cover - only on a broken install
        database = {"path": str(settings().db_path), "ok": False, "error": str(exc)}

    return {
        "status": "ok",
        "engine_version": ENGINE_VERSION,
        "today": date.today().isoformat(),
        "database": database,
        "packs": _discover_packs(),
        "default_pack": settings().default_pack,
        "assist_enabled": settings().assist_enabled,
    }


@router.get("/packs")
def packs() -> dict[str, Any]:
    """Packs available to the pack switcher."""
    return {"packs": _discover_packs(), "default": settings().default_pack}
