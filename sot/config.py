"""Runtime paths and settings.

Everything the engine needs to find on disk resolves through here, and every value can
be overridden by environment variable so tests can run against a scratch database and
landing directory without touching the developer's.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: Bumped when a change alters computed output for unchanged inputs. Recorded on every
#: run so a surprising diff can be traced to an engine change rather than the data.
ENGINE_VERSION = "0.1.0"

#: Fallback when neither the request nor the environment names one.
DEFAULT_PACK = "healthcare_ny"

#: Browsers are only ever served from the dev server or the API itself.
LOCALHOST_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _repo_root() -> Path:
    """Directory containing the ``sot`` package."""
    return _env_path("SOT_ROOT", Path(__file__).resolve().parent.parent)


@dataclass(frozen=True)
class Settings:
    """Resolved locations and feature switches for one process."""

    root: Path
    var_dir: Path
    landing_dir: Path
    pages_dir: Path
    reports_dir: Path
    packs_dir: Path
    data_dir: Path
    db_path: Path
    default_pack: str = DEFAULT_PACK
    assist_enabled: bool = False
    cors_origins: tuple[str, ...] = field(default_factory=lambda: LOCALHOST_ORIGINS)

    def ensure_dirs(self) -> None:
        """Create the writable directories. Safe to call repeatedly."""
        for path in (self.var_dir, self.landing_dir, self.pages_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)

    def pack_dir(self, pack: str) -> Path:
        """Directory of a named pack."""
        return self.packs_dir / pack


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Process-wide settings, resolved once from the environment."""
    root = _repo_root()
    var_dir = _env_path("SOT_VAR_DIR", root / "var")
    return Settings(
        root=root,
        var_dir=var_dir,
        landing_dir=_env_path("SOT_LANDING_DIR", var_dir / "landing"),
        pages_dir=_env_path("SOT_PAGES_DIR", var_dir / "pages"),
        reports_dir=_env_path("SOT_REPORTS_DIR", root / "reports"),
        packs_dir=_env_path("SOT_PACKS_DIR", root / "packs"),
        data_dir=_env_path("SOT_DATA_DIR", root / "data"),
        db_path=_env_path("SOT_DB_PATH", var_dir / "sot.duckdb"),
        default_pack=os.environ.get("SOT_DEFAULT_PACK", DEFAULT_PACK),
        # Assist features reach the network, so they stay off unless asked for twice:
        # an explicit setting and an API key.
        assist_enabled=os.environ.get("SOT_ASSIST_ENABLED", "").lower() in {"1", "true", "yes"},
    )


def reset_settings_cache() -> None:
    """Forget cached settings so a test can repoint the environment."""
    settings.cache_clear()
