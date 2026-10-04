"""DuckDB access.

One process owns one connection, guarded by a lock. DuckDB is fast enough that a
single writer is never the bottleneck at our scale, and serializing writes removes a
whole class of interleaving bugs that would otherwise show up as non-deterministic
output - the one thing the spec will not tolerate.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from sot.config import settings

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class Database:
    """A DuckDB file with the Source of Truth schema applied."""

    def __init__(self, path: str | Path | None = None, *, read_only: bool = False) -> None:
        self.path = Path(path) if path is not None else settings().db_path
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self.path), read_only=read_only)
        if not read_only:
            self.init_schema()

    # -- lifecycle ---------------------------------------------------------

    def init_schema(self) -> None:
        """Apply ``schema.sql``. Idempotent: every statement is CREATE IF NOT EXISTS."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.execute(sql)

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- reading -----------------------------------------------------------

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        """Run a SELECT and return rows as dictionaries."""
        with self._lock:
            cursor = self._conn.execute(sql, list(params) if params else None)
            columns = [desc[0] for desc in cursor.description or []]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
        """Run a SELECT and return the first row, or ``None``."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        """Run a SELECT and return the first column of the first row."""
        with self._lock:
            result = self._conn.execute(sql, list(params) if params else None).fetchone()
        return result[0] if result else None

    def table_names(self) -> list[str]:
        """Names of all tables and views in the database, sorted."""
        rows = self.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        return [row["table_name"] for row in rows]

    # -- writing -----------------------------------------------------------

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        """Run a statement for its effect."""
        with self._lock:
            self._conn.execute(sql, list(params) if params else None)

    def insert_rows(self, table: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """Insert dictionaries into ``table``, returning the row count.

        Columns are the sorted union of all keys, so a row that happens to omit an
        optional field does not change the shape of the statement, and the statement
        itself is identical between runs over the same data.
        """
        materialized = [dict(row) for row in rows]
        if not materialized:
            return 0
        columns = sorted({key for row in materialized for key in row})
        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(f'"{column}"' for column in columns)
        sql = f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders})'
        values = [tuple(row.get(column) for column in columns) for row in materialized]
        with self._lock:
            self._conn.executemany(sql, values)
        return len(values)

    def delete_run(self, run_id: str) -> None:
        """Remove every derived row for a run.

        Called before a rebuild so that re-running over the same inputs replaces the
        previous result rather than accumulating beside it. ``files`` and ``decisions``
        are untouched by design: landed content and human memory outlive runs.
        """
        with self._lock:
            for table in _RUN_SCOPED_TABLES:
                self._conn.execute(f'DELETE FROM "{table}" WHERE run_id = ?', [run_id])

    def truncate_all(self) -> None:
        """Empty every table, including files and decisions. Backs ``make reset``."""
        with self._lock:
            for table in (*_RUN_SCOPED_TABLES, "run_files", "files", "decisions", "runs"):
                self._conn.execute(f'DELETE FROM "{table}"')


#: Every table whose rows belong to a single run and are rebuilt wholesale.
_RUN_SCOPED_TABLES: tuple[str, ...] = (
    "raw_rows",
    "pdf_cells",
    "quarantine",
    "std_records",
    "shift_segments",
    "persons",
    "links",
    "claims",
    "golden_attributes",
    "credentials",
    "pay_lines",
    "match_person_week",
    "match_person_day",
    "daily_hours",
    "flags",
    "flag_evidence",
    "node_stats",
    "run_events",
)

_default_db: Database | None = None
_default_lock = threading.Lock()


def get_db() -> Database:
    """The process-wide database, opened on first use."""
    global _default_db
    with _default_lock:
        if _default_db is None:
            settings().ensure_dirs()
            _default_db = Database()
        return _default_db


def close_db() -> None:
    """Close and forget the process-wide database."""
    global _default_db
    with _default_lock:
        if _default_db is not None:
            _default_db.close()
            _default_db = None
