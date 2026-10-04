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
