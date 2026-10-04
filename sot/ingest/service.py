"""Ingestion: files in, standardized records and flags out.

The orchestration for the first half of the pipeline. Each source gets its own step so
the canvas can show it separately and a failure in one cannot touch the others - a
missing payroll column must never stop the roster from loading.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sot.canon import canonical_json
from sot.ids import digest, stable_id
from sot.ingest.contracts import Pack, header_key, load_pack
from sot.ingest.detect import MEDIA_PDF, MEDIA_TABULAR, Detection, classify_grid, is_xlsx
from sot.ingest.headers import HeaderMapping
from sot.ingest.landing import LandedFile, collect_input_paths, land_paths, record_run_files
from sot.ingest.reader import (
    Grid,
    classify_non_data,
    clean_cell,
    is_null_token,
    read_delimited,
    read_xlsx,
    repair_row,
)
from sot.pipeline.run import STATUS_DEGRADED, RunContext
from sot.rules.model import Entity, Evidence
from sot.store.db import Database, get_db

#: Columns whose emptiness marks a row as a subtotal rather than a record.
_IDENTIFIER_TYPES = ("person_name", "license_number", "string")
_NUMERIC_TYPES = ("hours", "integer")


@dataclass
class SourceRead:
    """What one file turned into."""

    landed: LandedFile
    detection: Detection
    records: list[dict[str, Any]] = field(default_factory=list)
    raw_rows: list[dict[str, Any]] = field(default_factory=list)
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    repaired: int = 0
    null_tokens: dict[str, int] = field(default_factory=dict)


@dataclass
class IngestResult:
    """The outcome of one ingest run."""

    run_id: str
    status: str
    as_of: date
    pack: str
    files: list[LandedFile] = field(default_factory=list)
    reads: list[SourceRead] = field(default_factory=list)
    record_count: int = 0
    quarantined_count: int = 0
    context: RunContext | None = None

    @property
    def flags(self) -> list[Any]:
        return self.context.flags.finalize() if self.context else []

    def codes(self) -> list[str]:
        return sorted({flag.rule_code for flag in self.flags})

    def flags_above_info(self) -> list[Any]:
        return [flag for flag in self.flags if flag.severity.is_above_info]


def _read_grid(landed: LandedFile) -> Grid:
    data = landed.data
    return read_xlsx(data) if is_xlsx(data) else read_delimited(data)


def _file_entity(landed: LandedFile) -> Entity:
    return Entity(type="file", id=landed.file_id, display=landed.original_name)


def ingest_paths(
    target: str | Path | Sequence[str | Path],
    *,
    pack_id: str | None = None,
    as_of: date | None = None,
    db: Database | None = None,
    type_overrides: dict[str, str] | None = None,
) -> IngestResult:
    """Ingest a directory, a file, or a list of them."""
    from sot.config import settings

    pack = load_pack(pack_id or settings().default_pack)
    as_of = as_of or date.today()
    db = db or get_db()
    overrides = {name.lower(): source for name, source in (type_overrides or {}).items()}

    targets: list[Path] = []
    if isinstance(target, (str, Path)):
        targets = collect_input_paths(target)
    else:
        for item in target:
            targets.extend(collect_input_paths(item))

    # Canonical order before anything is read. Without this the result depends on the
    # order files happened to be handed over: whichever copy of a duplicated file comes
    # first is the one kept, so the flag would name a different file run to run.
    targets = sorted(dict.fromkeys(targets), key=lambda path: (path.name, str(path)))

    # The digest is order-free, so the same files in a different order are the same run.
    input_digest = digest(
        {
            "files": sorted(path.name for path in targets),
            "as_of": as_of,
            "pack": pack.id,
        }
    )
    context = RunContext(pack, as_of, db, input_digest=input_digest)
    context.start()

    result = IngestResult(
        run_id=context.run_id, status="RUNNING", as_of=as_of, pack=pack.id, context=context
    )

    landed = _intake(context, db, targets, result, overrides, pack)
    _read_sources(context, db, landed, result, pack)

    result.status = context.finish()
    return result


def _intake(
    context: RunContext,
    db: Database,
    targets: list[Path],
    result: IngestResult,
    overrides: dict[str, str],
    pack: Pack,
) -> list[tuple[LandedFile, Detection]]:
    """Land every file and work out what each one is."""
    landed_with_detection: list[tuple[LandedFile, Detection]] = []

    with context.node("intake", "Intake", "source") as node:
        node.rows_in = len(targets)
        landed = land_paths(db, targets, context.run_id)
        result.files = landed

        for item in landed:
            if item.is_duplicate:
                context.flags.raise_flag(
                    "FILE_DUPLICATE",
                    {"filename": item.original_name, "original_name": item.first_seen_as},
                    entities=[_file_entity(item)],
                    evidence=[Evidence(file_id=item.file_id, source_type="unknown")],
                    key_parts=(item.file_id, item.original_name),
                    node_id="intake",
                )
                continue

            detection = _detect_one(item, pack, overrides)
            landed_with_detection.append((item, detection))

            if detection.media_kind == MEDIA_PDF:
                continue
            if not detection.ok:
                best = detection.best_alternatives(1)
                context.flags.raise_flag(
                    "FILE_TYPE_UNKNOWN",
                    {
                        "filename": item.original_name,
                        "best_source": best[0][0] if best else "nothing",
                        "best_score": best[0][1] if best else 0.0,
                        "threshold": float(pack.setting("detection.min_score", 0.5)),
                        "reason": detection.reason,
                    },
                    entities=[_file_entity(item)],
                    evidence=[Evidence(file_id=item.file_id)],
                    key_parts=(item.file_id,),
                    node_id="intake",
                )

        node.rows_out = len(landed_with_detection)
        record_run_files(
            db,
            context.run_id,
            landed,
            {item.file_id: det.source or "" for item, det in landed_with_detection},
        )
        for item, det in landed_with_detection:
            db.execute(
                "UPDATE files SET detected_source = ?, detect_confidence = ?, "
                "detect_method = ?, header_row_index = ? WHERE file_id = ?",
                [det.source, det.score, det.method, det.header_row_index, item.file_id],
            )

    return landed_with_detection


def _detect_one(item: LandedFile, pack: Pack, overrides: dict[str, str]) -> Detection:
    """Classify one landed file, honouring a manual override."""
    if item.media_kind == MEDIA_PDF:
        contract = next(iter(pack.contracts_for_role("schedule")), None)
        return Detection(
            MEDIA_PDF,
            source=contract.source if contract else "schedule",
            role="schedule",
            score=1.0,
            method="pdf",
            reason="PDF files are routed to the schedule adapter",
        )
    if item.media_kind != MEDIA_TABULAR:
        return Detection(item.media_kind, reason="not a format we can read")

    override = overrides.get(item.original_name.lower())
    try:
        grid = _read_grid(item)
    except Exception as exc:
        return Detection(MEDIA_TABULAR, reason=f"could not be read: {type(exc).__name__}: {exc}")
    return classify_grid(grid.rows, pack, override=override)


def _read_sources(
    context: RunContext,
    db: Database,
    landed: list[tuple[LandedFile, Detection]],
    result: IngestResult,
    pack: Pack,
) -> None:
    """Read each classified tabular file into standardized records.

    One step per source type, so the canvas shows them separately and a failure is
    contained: a payroll file missing its hours column must not stop the roster.
    """
    by_source: dict[str, list[tuple[LandedFile, Detection]]] = {}
    for item, detection in landed:
        if detection.media_kind == MEDIA_TABULAR and detection.ok and detection.source:
            by_source.setdefault(detection.source, []).append((item, detection))

    for source in sorted(by_source):
        contract = pack.contract(source)
        if contract is None:
            continue
        node_id = f"source_{source}"
        with context.node(node_id, contract.source.replace("_", " ").title(), "source") as node:
            for item, detection in by_source[source]:
                read = _read_one(context, item, detection, node_id, pack)
                result.reads.append(read)
                node.rows_in += len(read.raw_rows)
                node.rows_out += len(read.records)
                node.quarantined += len(read.quarantined)
                result.record_count += len(read.records)
                result.quarantined_count += len(read.quarantined)

                db.insert_rows("raw_rows", read.raw_rows)
                db.insert_rows("std_records", read.records)
                db.insert_rows("quarantine", read.quarantined)
            if node.quarantined:
                node.status = STATUS_DEGRADED


def _read_one(
    context: RunContext,
    item: LandedFile,
    detection: Detection,
    node_id: str,
    pack: Pack,
) -> SourceRead:
    """Read one file's data rows."""
    read = SourceRead(landed=item, detection=detection)
    grid = _read_grid(item)
    mapping = detection.mapping
    header_index = detection.header_row_index or 0
    header_row = grid.rows[header_index] if header_index < len(grid.rows) else []
    contract = pack.contract(detection.source or "")
    if mapping is None or contract is None:
        return read

    file_entity = _file_entity(item)
    db = context.db
    db.execute(
        "UPDATE files SET encoding = ?, delimiter = ? WHERE file_id = ?",
        [grid.encoding, grid.delimiter, item.file_id],
    )

    if grid.used_fallback:
        context.flags.raise_flag(
            "ENCODING_FALLBACK",
            {"filename": item.original_name, "encoding": grid.encoding},
            entities=[file_entity],
            evidence=[Evidence(file_id=item.file_id, source_type=contract.source)],
            key_parts=(item.file_id,),
            node_id=node_id,
        )

    _flag_header_problems(context, item, mapping, contract, node_id, file_entity)
    if mapping.missing_required:
        # A blocker for this file only. Nothing is read from it, and every other file
        # in the upload carries on.
        return read

    index_to_canonical = mapping.index_to_canonical
    name_indexes = mapping.indexes_of_type("person_name")
    numeric_indexes = set(mapping.indexes_of_type(*_NUMERIC_TYPES))
    identifier_indexes = {
        match.index
        for match in mapping.by_canonical.values()
        if match.column and match.column.type in _IDENTIFIER_TYPES and match.column.required
    }
    expected = len(header_row)
    repaired_examples: list[str] = []
    null_token_examples: set[str] = set()

    for offset, row in enumerate(grid.rows[header_index + 1 :], start=header_index + 2):
        # 1-based physical line, which is what the user sees in a spreadsheet.
        row_index = offset
        reason = classify_non_data(row, header_row, numeric_indexes, identifier_indexes)
        if reason is not None:
            read.dropped[reason] = read.dropped.get(reason, 0) + 1
            read.raw_rows.append(
                _raw_row(context.run_id, item, row_index, header_row, row, "dropped", reason)
            )
            continue

        fields = list(row)
        if len(fields) != expected:
            repair = repair_row(fields, expected, name_indexes=name_indexes)
            if repair.repaired:
                fields = repair.fields
                read.repaired += 1
                if len(repaired_examples) < 3:
                    repaired_examples.append(repair.merged_value)
            else:
                read.quarantined.append(
                    {
                        "run_id": context.run_id,
                        "file_id": item.file_id,
                        "row_index": row_index,
                        "rule_code": "ROW_FIELD_COUNT_MISMATCH",
                        "raw_text": ",".join(fields)[:500],
                        "field_count": len(fields),
                        "expected_count": expected,
                    }
                )
                context.flags.raise_flag(
                    "ROW_FIELD_COUNT_MISMATCH",
                    {
                        "filename": item.original_name,
                        "row_index": row_index,
                        "found": len(fields),
                        "expected": expected,
                    },
                    entities=[file_entity],
                    evidence=[
                        Evidence(
                            file_id=item.file_id,
                            source_type=contract.source,
                            row_index=row_index,
                            raw_value=",".join(fields)[:200],
                        )
                    ],
                    key_parts=(item.file_id, str(row_index)),
                    node_id=node_id,
                )
                read.raw_rows.append(
                    _raw_row(
                        context.run_id,
                        item,
                        row_index,
                        header_row,
                        row,
                        "quarantined",
                        "field count mismatch",
                    )
                )
                continue

        raw: dict[str, str] = {}
        payload: dict[str, str] = {}
        for position, value in enumerate(fields):
            heading = header_row[position] if position < len(header_row) else f"column{position}"
            raw[str(heading)] = value
            if is_null_token(value):
                null_token_examples.add(value.strip() or "(empty)")
                read.null_tokens[str(heading)] = read.null_tokens.get(str(heading), 0) + 1
            canonical = index_to_canonical.get(position)
            cleaned = clean_cell(value)
            if canonical:
                payload[canonical] = cleaned
            elif cleaned:
                # An unrecognised column is kept rather than dropped: it may be the one
                # thing that explains a discrepancy later.
                payload[f"extra.{header_key(str(heading)) or position}"] = cleaned

        record_id = stable_id("SR", {"file": item.file_id, "row": row_index})
        read.records.append(
            {
                "run_id": context.run_id,
                "record_id": record_id,
                "source_type": contract.source,
                "source_role": contract.role,
                "file_id": item.file_id,
                "row_index": row_index,
                "payload_json": canonical_json(payload),
                "raw_json": canonical_json(raw),
            }
        )
        read.raw_rows.append(
            _raw_row(context.run_id, item, row_index, header_row, row, "ok", None, payload)
        )

    _flag_row_problems(
        context, item, read, contract, node_id, file_entity, repaired_examples, null_token_examples
    )
    return read


def _raw_row(
    run_id: str,
    item: LandedFile,
    row_index: int,
    header: list[str],
    row: list[str],
    status: str,
    note: str | None,
    payload: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw = {
        str(header[i]) if i < len(header) else f"column{i}": value for i, value in enumerate(row)
    }
    return {
        "run_id": run_id,
        "file_id": item.file_id,
        "row_index": row_index,
        "raw_json": canonical_json(raw),
        "norm_json": canonical_json(payload or {}),
        "status": status,
        "note": note,
    }


def _flag_header_problems(
    context: RunContext,
    item: LandedFile,
    mapping: HeaderMapping,
    contract,
    node_id: str,
    file_entity: Entity,
) -> None:
    """Report whatever the header row did not give us."""
    if mapping.missing_required:
        context.flags.raise_flag(
            "HEADER_REQUIRED_MISSING",
            {
                "filename": item.original_name,
                "column": ", ".join(mapping.missing_required),
                "source": contract.source,
            },
            entities=[file_entity],
            evidence=[Evidence(file_id=item.file_id, source_type=contract.source)],
            key_parts=(item.file_id, *mapping.missing_required),
            node_id=node_id,
        )

    for canonical, losers in sorted(mapping.ambiguous.items()):
        winner = mapping.by_canonical.get(canonical)
        context.flags.raise_flag(
            "HEADER_AMBIGUOUS",
            {
                "filename": item.original_name,
                "columns": ", ".join(sorted({match.raw for match in [*losers, winner] if match})),
                "field": canonical,
                "chosen": winner.raw if winner else "",
            },
            entities=[file_entity],
            evidence=[
                Evidence(
                    file_id=item.file_id,
                    source_type=contract.source,
                    column_name=match.raw,
                )
                for match in losers
            ],
            key_parts=(item.file_id, canonical),
            node_id=node_id,
        )

    if mapping.unmapped:
        names = sorted({match.raw for match in mapping.unmapped})
        context.flags.raise_flag(
            "HEADER_UNMAPPED_COLUMN",
            {
                "filename": item.original_name,
                "source": contract.source,
                "columns": ", ".join(names),
                "count": len(names),
                "file_id": item.file_id,
            },
            entities=[file_entity],
            evidence=[
                Evidence(file_id=item.file_id, source_type=contract.source, column_name=name)
                for name in names
            ],
            node_id=node_id,
        )


def _flag_row_problems(
    context: RunContext,
    item: LandedFile,
    read: SourceRead,
    contract,
    node_id: str,
    file_entity: Entity,
    repaired_examples: list[str],
    null_token_examples: set[str],
) -> None:
    """Report what reading the rows turned up, aggregated per file."""
    if read.repaired:
        context.flags.raise_flag(
            "ROW_DELIMITER_REPAIRED",
            {
                "filename": item.original_name,
                "count": read.repaired,
                "example": repaired_examples[0] if repaired_examples else "",
                "file_id": item.file_id,
            },
            entities=[file_entity],
            node_id=node_id,
        )

    if read.dropped:
        breakdown = ", ".join(f"{count} {reason}" for reason, count in sorted(read.dropped.items()))
        context.flags.raise_flag(
            "ROW_DROPPED_NONDATA",
            {
                "filename": item.original_name,
                "count": sum(read.dropped.values()),
                "breakdown": breakdown,
                "file_id": item.file_id,
            },
            entities=[file_entity],
            node_id=node_id,
        )

    if read.null_tokens:
        context.flags.raise_flag(
            "NULL_TOKEN",
            {
                "filename": item.original_name,
                "count": sum(read.null_tokens.values()),
                "tokens": ", ".join(sorted(null_token_examples)[:5]),
                "file_id": item.file_id,
            },
            entities=[file_entity],
            node_id=node_id,
        )
