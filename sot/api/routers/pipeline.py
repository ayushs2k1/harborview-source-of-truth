"""The pipeline graph, and the parameters the UI is allowed to change.

Spec principle 8: the graph is a view of the config and a safe editor of it, not
where the logic lives. Edits are parameters only - thresholds, windows, tolerances -
validated before they are saved and written to an overrides file so the pack's own
defaults stay as shipped and the change can be undone by deleting one file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sot.api import deps
from sot.config import settings
from sot.ingest.contracts import clear_pack_cache, load_pack
from sot.pipeline.spec import PipelineError, pipeline_for_pack, with_stats

router = APIRouter(tags=["pipeline"])

#: Parameters the UI may change, with the type and range each must satisfy.
#: Anything not listed here cannot be edited through the API at all - structural
#: changes are a code change, not a form field.
EDITABLE: dict[str, dict[str, Any]] = {
    "hours_tolerance": {
        "type": float,
        "min": 0.0,
        "max": 8.0,
        "label": "Hours tolerance",
        "unit": "hours",
    },
    "rn_min_consecutive_hours": {
        "type": float,
        "min": 0.0,
        "max": 24.0,
        "label": "RN consecutive hours required",
        "unit": "hours",
    },
    "verification_max_age_days": {
        "type": int,
        "min": 1,
        "max": 3650,
        "label": "Verification valid for",
        "unit": "days",
    },
    "pbj.daily_cap_hours": {
        "type": float,
        "min": 1.0,
        "max": 24.0,
        "label": "Daily hours cap",
        "unit": "hours",
    },
    "pbj.traceability_variance_pct": {
        "type": float,
        "min": 0.0,
        "max": 100.0,
        "label": "Traceability tolerance",
        "unit": "%",
    },
    "pbj.meal_deduction.minutes": {
        "type": int,
        "min": 0,
        "max": 120,
        "label": "Meal deduction",
        "unit": "minutes",
    },
    "pbj.meal_deduction.min_shift_hours": {
        "type": float,
        "min": 0.0,
        "max": 24.0,
        "label": "Meal applies from",
        "unit": "hours",
    },
    "pbj.include_training": {"type": bool, "label": "Count training as reported hours"},
    "pbj.split_at_midnight": {"type": bool, "label": "Split overnight shifts at midnight"},
    "zero_rn_days.warn": {"type": int, "min": 0, "max": 92, "label": "Zero-RN days warning"},
    "zero_rn_days.critical": {"type": int, "min": 0, "max": 92, "label": "Zero-RN days critical"},
    "matching.bands.auto": {"type": float, "min": 0.0, "max": 40.0, "label": "Auto-link score"},
    "matching.bands.review": {"type": float, "min": 0.0, "max": 40.0, "label": "Review score"},
    "matching.ambiguous_margin": {
        "type": float,
        "min": 0.0,
        "max": 20.0,
        "label": "Ambiguity margin",
    },
}


class ParamsIn(BaseModel):
    pack: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


def overrides_path() -> Path:
    return settings().var_dir / "overrides.yaml"


def load_overrides() -> dict[str, Any]:
    path = overrides_path()
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@router.get("/pipeline")
def get_pipeline(pack: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    """The graph, plus the latest run's numbers on each step."""
    database = deps.db()
    resolved_run = deps.resolve_run_id(database, run_id)
    pack_id = pack
    if pack_id is None and resolved_run:
        row = database.query_one("SELECT pack FROM runs WHERE run_id = ?", [resolved_run])
        pack_id = row["pack"] if row else None
    pack_id = pack_id or settings().default_pack

    try:
        spec = pipeline_for_pack(load_pack(pack_id))
    except (PipelineError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    stats: dict[str, dict[str, Any]] = {}
    if resolved_run:
        for row in database.query("SELECT * FROM node_stats WHERE run_id = ?", [resolved_run]):
            stats[row["node_id"]] = {
                "status": row["status"],
                "rows_in": row["rows_in"],
                "rows_out": row["rows_out"],
                "quarantined": row["quarantined"],
                "duration_ms": row["duration_ms"],
                "flags": {
                    "BLOCKER": row["flags_blocker"],
                    "CRITICAL": row["flags_critical"],
                    "WARNING": row["flags_warning"],
                    "INFO": row["flags_info"],
                },
                "error": row["error"],
            }

    payload = with_stats(spec, stats)
    payload["pack"] = pack_id
    payload["run_id"] = resolved_run
    return payload


@router.get("/pipeline/params")
def get_params(pack: str | None = None) -> dict[str, Any]:
    """Every editable parameter, its current value, and what it may be set to."""
    pack_id = pack or settings().default_pack
    loaded = load_pack(pack_id)
    overrides = load_overrides().get(pack_id, {})
    return {
        "pack": pack_id,
        "params": [
            {
                "key": key,
                "label": rule.get("label", key),
                "unit": rule.get("unit", ""),
                "type": rule["type"].__name__,
                "min": rule.get("min"),
                "max": rule.get("max"),
                "value": loaded.setting(key),
                "overridden": key in overrides,
                "default": _default_for(pack_id, key),
            }
            for key, rule in sorted(EDITABLE.items())
        ],
    }


def _default_for(pack_id: str, key: str) -> Any:
    """The shipped value, read straight from the pack file rather than the override."""
    manifest = settings().pack_dir(pack_id) / "pack.yaml"
    if not manifest.is_file():
        return None
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@router.put("/pipeline/params")
def put_params(payload: ParamsIn) -> dict[str, Any]:
    """Change parameters, after checking every one of them.

    Validated against the declared type and range before anything is written, and
    written to an overrides file rather than into the pack - so the shipped defaults
    stay visible and the whole change is undone by deleting one file.
    """
    pack_id = payload.pack or settings().default_pack
    errors: list[str] = []
    cleaned: dict[str, Any] = {}

    for key, value in payload.values.items():
        rule = EDITABLE.get(key)
        if rule is None:
            errors.append(f"{key} is not an editable parameter")
            continue
        try:
            coerced = rule["type"](value)
        except (TypeError, ValueError):
            errors.append(f"{key} must be a {rule['type'].__name__}, got {value!r}")
            continue
        if "min" in rule and coerced < rule["min"]:
            errors.append(f"{key} must be at least {rule['min']}")
            continue
        if "max" in rule and coerced > rule["max"]:
            errors.append(f"{key} must be at most {rule['max']}")
            continue
        cleaned[key] = coerced

    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    overrides = load_overrides()
    overrides.setdefault(pack_id, {}).update(cleaned)
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(overrides, sort_keys=True), encoding="utf-8")

    _apply_overrides(pack_id, overrides.get(pack_id, {}))
    return {"pack": pack_id, "updated": sorted(cleaned), "applies_from": "the next run"}


def _apply_overrides(pack_id: str, values: dict[str, Any]) -> None:
    """Push the overrides into the loaded pack so the next run uses them."""
    clear_pack_cache()
    loaded = load_pack(pack_id)
    for key, value in values.items():
        node = loaded.settings
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


@router.delete("/pipeline/params")
def reset_params(pack: str | None = None) -> dict[str, Any]:
    """Put everything back to the pack's shipped values."""
    pack_id = pack or settings().default_pack
    overrides = load_overrides()
    overrides.pop(pack_id, None)
    path = overrides_path()
    if overrides:
        path.write_text(yaml.safe_dump(overrides, sort_keys=True), encoding="utf-8")
    elif path.exists():
        path.unlink()
    clear_pack_cache()
    return {"pack": pack_id, "reset": True}
