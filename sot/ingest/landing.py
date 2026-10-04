"""Immutable file landing.

Every file is stored under its own content hash before anything is read from it, and
the stored copy is never modified. Two consequences matter. Evidence stays valid: a
flag raised three runs ago still points at the exact bytes it was raised from, even if
someone has since edited the file on their desktop. And identity follows content, so
the same export uploaded under two names is recognisably one file.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sot.config import settings
from sot.ids import file_id as make_file_id
from sot.ingest.detect import detect_media_kind
from sot.store.db import Database

#: Extensions we will try to read. Anything else is still landed and still flagged,
#: because telling someone their file was ignored beats ignoring it silently.
READABLE_SUFFIXES = frozenset({".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".pdf"})

#: Never treat these as input, whatever directory they turn up in.
IGNORED_NAMES = frozenset({".DS_Store", "Thumbs.db", ".gitkeep"})


@dataclass(frozen=True)
class LandedFile:
    """One file, stored and registered."""

    file_id: str
    sha256: str
    original_name: str
    stored_path: Path
    size_bytes: int
    media_kind: str
    #: True when the same bytes arrived more than once in this upload.
    is_duplicate: bool = False
    #: The name this content first arrived under, when it is a duplicate.
    first_seen_as: str | None = None
    first_seen_run: str | None = None

    @property
    def data(self) -> bytes:
        return self.stored_path.read_bytes()


def collect_input_paths(target: str | Path) -> list[Path]:
    """Every candidate file under a path, in a stable order.

    Sorted by name so that a run over a directory reads files in the same order every
    time. Order should not change the result - and a test asserts it does not - but a
    stable order makes logs and event streams comparable between runs.
    """
    root = Path(target)
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name not in IGNORED_NAMES and not path.name.startswith(".")
    )


def land_file(
    db: Database,
    data: bytes,
    original_name: str,
    run_id: str,
    *,
    seen_hashes: dict[str, str] | None = None,
) -> LandedFile:
    """Store one file by content hash and register it.

    ``seen_hashes`` maps a hash to the name it first arrived under *in this run*. A
    repeat within one upload is a duplicate; the same file ingested again in a later
    run is not, because re-running over the same inputs is the normal case and
    flagging it every time would be noise.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    identifier = make_file_id(sha256)
    destination = settings().landing_dir / sha256 / original_name
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".part")
        tmp.write_bytes(data)
        shutil.move(str(tmp), str(destination))

    existing = db.query_one(
        "SELECT original_name, first_seen_run FROM files WHERE file_id = ?", [identifier]
    )
    first_seen_as = seen_hashes.get(sha256) if seen_hashes is not None else None
    is_duplicate = first_seen_as is not None
    if seen_hashes is not None and not is_duplicate:
        seen_hashes[sha256] = original_name

    media_kind = detect_media_kind(data, original_name)
    if existing is None:
        db.insert_rows(
            "files",
            [
                {
                    "file_id": identifier,
                    "sha256": sha256,
                    "original_name": original_name,
                    "stored_path": str(destination),
                    "size_bytes": len(data),
                    "media_kind": media_kind,
                    "first_seen_run": run_id,
                    "last_seen_run": run_id,
                    "first_seen_at": datetime.now(),
                }
            ],
        )
    else:
        db.execute("UPDATE files SET last_seen_run = ? WHERE file_id = ?", [run_id, identifier])

    return LandedFile(
        file_id=identifier,
        sha256=sha256,
        original_name=original_name,
        stored_path=destination,
        size_bytes=len(data),
        media_kind=media_kind,
        is_duplicate=is_duplicate,
        first_seen_as=first_seen_as,
        first_seen_run=existing["first_seen_run"] if existing else run_id,
    )


def land_paths(db: Database, paths: list[Path], run_id: str) -> list[LandedFile]:
    """Land a list of files, detecting repeats within the upload."""
    seen: dict[str, str] = {}
    return [land_file(db, path.read_bytes(), path.name, run_id, seen_hashes=seen) for path in paths]


def record_run_files(
    db: Database, run_id: str, landed: list[LandedFile], sources: dict[str, str]
) -> None:
    """Record which files took part in this run, and as what."""
    db.insert_rows(
        "run_files",
        [
            {
                "run_id": run_id,
                "file_id": item.file_id,
                "source_type": sources.get(item.file_id),
                "is_duplicate": item.is_duplicate,
            }
            for item in landed
            # A duplicate shares its file_id with the original, and run_files is keyed
            # on the pair, so the repeat is recorded by the original's row.
            if not item.is_duplicate
        ],
    )
