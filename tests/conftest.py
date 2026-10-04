"""Shared test fixtures.

The environment is repointed at a scratch directory *before* anything imports ``sot``,
so a test run can never write to the developer's database, landing directory, or
reports. ``sot.config.settings`` caches on first use, which is why this happens at
import time rather than in a fixture.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_SCRATCH = Path(tempfile.mkdtemp(prefix="sot-tests-"))
os.environ.setdefault("SOT_VAR_DIR", str(_SCRATCH / "var"))
os.environ.setdefault("SOT_DB_PATH", str(_SCRATCH / "var" / "test.duckdb"))
os.environ.setdefault("SOT_LANDING_DIR", str(_SCRATCH / "var" / "landing"))
os.environ.setdefault("SOT_PAGES_DIR", str(_SCRATCH / "var" / "pages"))
os.environ.setdefault("SOT_REPORTS_DIR", str(_SCRATCH / "reports"))

from sot.store.db import Database  # noqa: E402  (must follow the env setup above)

#: Repository root, for tests that read source or fixture files.
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _cleanup_scratch():
    yield
    shutil.rmtree(_SCRATCH, ignore_errors=True)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """A fresh database per test, on disk so the real file path logic is exercised."""
    database = Database(tmp_path / "test.duckdb")
    yield database
    database.close()


@pytest.fixture()
def repo_root() -> Path:
    """Path to the repository root."""
    return REPO_ROOT


@pytest.fixture()
def pack():
    """The healthcare pack, loaded from the repository."""
    from sot.ingest.contracts import load_pack

    return load_pack("healthcare_ny", packs_dir=str(REPO_ROOT / "packs"))


@pytest.fixture()
def make_files(tmp_path: Path):
    """Write a dict of ``name -> text or bytes`` into a fresh directory."""

    def build(files: dict[str, str | bytes], folder: str = "input") -> Path:
        target = tmp_path / folder
        target.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            path = target / name
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        return target

    return build


@pytest.fixture()
def sample_dir() -> Path:
    """The committed healthcare fixtures."""
    return REPO_ROOT / "data" / "samples" / "healthcare"
