"""Ingestion: files in, standardized records and flags out.

The orchestration for the first half of the pipeline. Each source gets its own step so
the canvas can show it separately and a failure in one cannot touch the others - a
missing payroll column must never stop the roster from loading.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
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
from sot.normalize.apply import KNOWN_TYPES, build_context, derived_fields, normalize_value, render
from sot.normalize.result import Quality
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
    #: Normalizer outcomes per canonical column, for the aggregated flags.
    qualities: dict[str, dict[str, int]] = field(default_factory=dict)


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
    segment_count: int = 0
    resolution: Any = None
    golden: Any = None
    match: Any = None
    staffing: Any = None
    summaries: list[Any] = field(default_factory=list)
    expirations: Any = None
    #: Shift segments as stored, with their resolved person attached. The copies the
    #: adapter produced have no person on them, because resolution had not run yet.
    segments: list[Any] = field(default_factory=list)
    credentials: list[Any] = field(default_factory=list)
    pay_lines: list[Any] = field(default_factory=list)
    schedules: list[Any] = field(default_factory=list)
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
    on_start: Callable[[RunContext], None] | None = None,
) -> IngestResult:
    """Ingest a directory, a file, or a list of them.

    ``on_start`` is handed the run as soon as it has an identifier and an event log,
    before any work happens. That is what lets the browser subscribe to a run it has
    only just asked for rather than waiting for it to finish.
    """
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
    if on_start is not None:
        on_start(context)

    result = IngestResult(
        run_id=context.run_id, status="RUNNING", as_of=as_of, pack=pack.id, context=context
    )

    landed = _intake(context, db, targets, result, overrides, pack)
    _read_sources(context, db, landed, result, pack)
    _read_schedules(context, db, landed, result, pack)
    _resolve_identities(context, db, result, pack)
    _report_missing_sources(context, result, pack)
    _build_ledger_and_match(context, db, result, pack)

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
    pending: list[tuple[int, dict[str, str], dict[str, str]]] = []

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
        cleaned_row: dict[str, str] = {}
        for position, value in enumerate(fields):
            heading = header_row[position] if position < len(header_row) else f"column{position}"
            raw[str(heading)] = value
            if is_null_token(value):
                null_token_examples.add(value.strip() or "(empty)")
                read.null_tokens[str(heading)] = read.null_tokens.get(str(heading), 0) + 1
            canonical = index_to_canonical.get(position)
            cleaned = clean_cell(value)
            if canonical:
                cleaned_row[canonical] = cleaned
            elif cleaned:
                # An unrecognised column is kept rather than dropped: it may be the one
                # thing that explains a discrepancy later.
                cleaned_row[f"extra.{header_key(str(heading)) or position}"] = cleaned

        pending.append((row_index, raw, cleaned_row))

    _normalize_rows(context, item, read, contract, node_id, file_entity, pending, header_row, pack)
    _flag_row_problems(
        context, item, read, contract, node_id, file_entity, repaired_examples, null_token_examples
    )
    return read


def _normalize_rows(
    context: RunContext,
    item: LandedFile,
    read: SourceRead,
    contract,
    node_id: str,
    file_entity: Entity,
    pending: list[tuple[int, dict[str, str], dict[str, str]]],
    header_row: list[str],
    pack: Pack,
) -> None:
    """Second pass: apply the contract's types, now that the whole column is visible.

    Done after reading rather than during, because a column has to be seen as a whole
    before any value in it can be read properly - one date with a day above twelve
    settles the order for the rest, and that is evidence rather than a guess.
    """
    by_column: dict[str, list[str]] = {}
    for _, _, cleaned in pending:
        for name, value in cleaned.items():
            by_column.setdefault(name, []).append(value)
    file_context = build_context(contract, by_column, pack)

    columns = contract.by_name
    name_column = next(
        (column.name for column in contract.columns if column.type == "person_name"), None
    )
    examples: dict[str, str] = {}

    for row_index, raw, cleaned in pending:
        payload: dict[str, str] = {}
        qualities: dict[str, str] = {}
        display_name = cleaned.get(name_column or "", "") or ""

        for name, value in sorted(cleaned.items()):
            column = columns.get(name)
            if column is None or column.type not in KNOWN_TYPES:
                payload[name] = value
                continue

            result = normalize_value(column, value, pack=pack, context=file_context, row=cleaned)
            payload[name] = render(result.value)
            payload.update(derived_fields(column, result.value))
            if result.quality is not Quality.OK:
                qualities[name] = str(result.quality)
                read.qualities.setdefault(name, {}).setdefault(str(result.quality), 0)
                read.qualities[name][str(result.quality)] += 1
                examples.setdefault(f"{name}:{result.quality}", value)
            if result.code:
                _raise_value_flag(
                    context,
                    item,
                    contract,
                    node_id,
                    file_entity,
                    column,
                    result,
                    row_index=row_index,
                    raw_value=value,
                    display_name=display_name,
                )

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
                "quality_json": canonical_json(qualities),
            }
        )
        read.raw_rows.append(
            _raw_row(
                context.run_id, item, row_index, header_row, list(raw.values()), "ok", None, payload
            )
        )


def _raise_value_flag(
    context: RunContext,
    item: LandedFile,
    contract,
    node_id: str,
    file_entity: Entity,
    column,
    result,
    *,
    row_index: int,
    raw_value: str,
    display_name: str,
) -> None:
    """Raise whatever rule a normalizer named, with the values its message needs."""
    params = {
        "filename": item.original_name,
        "file_id": item.file_id,
        "column": column.name,
        "row_index": row_index,
        "raw_value": raw_value,
        "display_name": display_name or f"row {row_index}",
        "count": 1,
        "example": raw_value,
        "converted": render(result.value),
        "code": raw_value,
        "note": result.note,
        "hours": result.value if column.type == "hours" else None,
        "order": result.note.split()[-4] if "assumed from" in result.note else "",
        "basis": result.note.split("assumed from", 1)[-1].strip()
        if "assumed from" in result.note
        else "",
        "credential_type": getattr(result.value, "credential_type", ""),
        "prefix_type": getattr(result.value, "prefix", ""),
        "number": render(result.value),
    }
    context.flags.raise_flag(
        result.code,
        params,
        entities=[file_entity],
        evidence=[
            Evidence(
                file_id=item.file_id,
                source_type=contract.source,
                row_index=row_index,
                column_name=column.name,
                raw_value=raw_value,
            )
        ],
        key_parts=(item.file_id, column.name, str(row_index)),
        node_id=node_id,
    )


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


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def _read_schedules(
    context: RunContext,
    db: Database,
    landed: list[tuple[LandedFile, Detection]],
    result: IngestResult,
    pack: Pack,
) -> None:
    """Read every PDF through the schedule adapter.

    Runs after the tabular sources because it needs two things from them: the payroll
    periods, which are what resolve a printed rota's missing year, and the roster's
    home facilities, which are what identify a page whose title does not name one.
    """
    pdfs = [(item, det) for item, det in landed if det.media_kind == MEDIA_PDF]
    if not pdfs:
        return

    from sot.adapters.schedule_pdf import extract_schedule

    period_hints = _payroll_periods(result)
    home_facilities = _home_facilities(result, pack)
    facilities = pack.crosswalk("facilities")
    roles = pack.crosswalk("roles")
    shift_codes = pack.setting("shift_codes")

    with context.node("source_schedule", "Schedule", "source") as node:
        for item, detection in pdfs:
            source_type = detection.source or "schedule"
            extracted = extract_schedule(
                item.data,
                file_id=item.file_id,
                source_type=source_type,
                as_of=context.as_of,
                facilities=facilities,
                roles=roles,
                shift_codes=shift_codes,
                period_hints=period_hints,
                home_facility_by_key=home_facilities,
            )

            node.rows_in += sum(len(page.rows) for page in extracted.pages)
            node.rows_out += len(extracted.segments)

            db.insert_rows(
                "pdf_cells",
                [{"run_id": context.run_id, **cell} for cell in extracted.cells],
            )
            db.insert_rows(
                "shift_segments",
                [{"run_id": context.run_id, **segment} for segment in extracted.segments],
            )
            db.execute(
                "UPDATE files SET page_count = ? WHERE file_id = ?",
                [len(extracted.pages), item.file_id],
            )

            _raise_adapter_findings(
                context, item, extracted.findings, source_type, "source_schedule"
            )
            if any(not page.readable for page in extracted.pages):
                node.status = STATUS_DEGRADED
            result.segment_count += len(extracted.segments)
            result.schedules.append(extracted)


def _payroll_periods(result: IngestResult) -> list[tuple[date, date]]:
    """Pay periods already read, used to resolve the rota's missing year."""
    import json

    periods: set[tuple[date, date]] = set()
    for read in result.reads:
        if read.detection.role != "payroll":
            continue
        for record in read.records:
            payload = json.loads(record["payload_json"])
            start, end = payload.get("period_start"), payload.get("period_end")
            if start and end:
                try:
                    periods.add((date.fromisoformat(start), date.fromisoformat(end)))
                except ValueError:
                    continue
    return sorted(periods)


def _home_facilities(result: IngestResult, pack: Pack) -> dict[str, str]:
    """Where each person on the roster usually works, keyed by folded name."""
    import json

    from sot.normalize.names import name_key

    crosswalk = pack.crosswalk("facilities")
    table: dict[str, str] = {}
    for read in result.reads:
        if read.detection.role != "roster":
            continue
        for record in read.records:
            payload = json.loads(record["payload_json"])
            full = payload.get("employee_name") or " ".join(
                part for part in (payload.get("first_name"), payload.get("last_name")) if part
            )
            facility = payload.get("facility") or payload.get("facility_code") or ""
            code = facility if crosswalk is None else (crosswalk.resolve(facility) or facility)
            if full and code:
                table[name_key(full)] = code
    return table


def _raise_adapter_findings(
    context: RunContext,
    item: LandedFile,
    findings: Sequence[Any],
    source_type: str,
    node_id: str,
) -> None:
    """Turn an adapter's findings into flags."""
    file_entity = _file_entity(item)
    for finding in findings:
        params = {"filename": item.original_name, "file_id": item.file_id, **finding.params}
        evidence = [
            Evidence(
                file_id=item.file_id,
                source_type=source_type,
                page=finding.page,
                row_index=finding.row_index,
                column_name=finding.column,
                raw_value=finding.raw_value,
                bbox=finding.bbox,
            )
        ]
        key_parts = finding.key_parts or (item.file_id, finding.code)
        context.flags.raise_flag(
            finding.code,
            params,
            entities=[file_entity],
            evidence=evidence,
            key_parts=(item.file_id, *key_parts),
            node_id=node_id,
        )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def _records_for_role(result: IngestResult, role: str) -> list[dict[str, Any]]:
    """Every standardized record of one source role, in a stable order."""
    records = [
        record for read in result.reads if read.detection.role == role for record in read.records
    ]
    return sorted(records, key=lambda item: (item["file_id"], item["row_index"]))


def _resolve_identities(
    context: RunContext, db: Database, result: IngestResult, pack: Pack
) -> None:
    """Work out who is who, and attach every record to a person."""
    from sot.decisions.store import load_decisions
    from sot.resolve.assign import check_credentials_in_service, resolve
    from sot.resolve.build import (
        build_credential_mentions,
        build_payroll_mentions,
        build_persons,
        build_schedule_mentions,
        person_rows,
    )
    from sot.resolve.scoring import MatchConfig

    roster = _records_for_role(result, "roster")
    payroll = _records_for_role(result, "payroll")
    credentials = _records_for_role(result, "credentials")
    segments = [segment for extract in result.schedules for segment in extract.segments]
    if not roster and not payroll and not credentials and not segments:
        return

    config = MatchConfig.from_pack(pack)
    decisions = load_decisions(db)

    with context.node("resolve", "Identity", "resolve") as node:
        persons = build_persons(roster, pack)
        mentions = [
            *build_payroll_mentions(payroll),
            *build_credential_mentions(credentials),
            *build_schedule_mentions(segments, pack),
        ]
        node.rows_in = len(mentions)

        resolution = resolve(
            persons, mentions, config, decisions=decisions, roster_supplied=bool(roster)
        )
        result.resolution = resolution
        node.rows_out = len(resolution.links)

        service_keys = {
            (mention.credential_key or "").upper()
            for mention in mentions
            if mention.source_role == "credentials" and mention.credential_key
        }
        resolution.findings.extend(check_credentials_in_service(persons, service_keys))

        db.insert_rows("persons", person_rows(context.run_id, resolution.persons))
        db.insert_rows("links", [link.as_row(context.run_id) for link in resolution.links])
        _attach_person_ids(db, context.run_id, resolution, mentions)
        _raise_resolution_findings(context, resolution, "resolve")

        context.progress("resolve", persons=len(resolution.persons), links=len(resolution.links))


def _attach_person_ids(db: Database, run_id: str, resolution: Any, mentions: Sequence[Any]) -> None:
    """Write the resolved person back onto the records it came from."""
    by_record = {link.record_id: link.person_id for link in resolution.links}
    by_id = {mention.record_id: mention for mention in mentions}

    for record_id, person_id in sorted(by_record.items()):
        mention = by_id.get(record_id)
        if mention is None:
            continue
        if mention.source_role == "schedule":
            for segment_id in mention.extra.get("segment_ids", ()):
                db.execute(
                    "UPDATE shift_segments SET person_id = ? WHERE run_id = ? AND segment_id = ?",
                    [person_id, run_id, segment_id],
                )
        else:
            db.execute(
                "UPDATE std_records SET person_id = ? WHERE run_id = ? AND record_id = ?",
                [person_id, run_id, record_id],
            )

    for person in resolution.persons:
        if person.record_id:
            db.execute(
                "UPDATE std_records SET person_id = ? WHERE run_id = ? AND record_id = ?",
                [person.person_id, run_id, person.record_id],
            )


def _raise_resolution_findings(context: RunContext, resolution: Any, node_id: str) -> None:
    """Turn resolution findings into flags."""
    for finding in resolution.findings:
        context.flags.raise_flag(
            finding.code,
            dict(finding.params),
            entities=list(finding.entities),
            evidence=[
                Evidence(
                    row_index=finding.row_index,
                    page=finding.page,
                    column_name=finding.column,
                    raw_value=finding.raw_value,
                )
            ]
            if (finding.row_index or finding.page or finding.raw_value)
            else [],
            key_parts=finding.key_parts or (finding.code,),
            node_id=node_id,
        )


#: What is lost when a source is absent, for the message.
_MISSING_CONSEQUENCE = {
    "roster": "nobody can be confirmed as employed and every other source stands alone.",
    "payroll": "no paid hours can be compared against the rota.",
    "credentials": "no credential can be verified against the issuing service.",
    "schedule": "there is no record of who was rostered, so paid hours cannot be placed on a day.",
}


def _report_missing_sources(context: RunContext, result: IngestResult, pack: Pack) -> None:
    """Report a source nobody supplied, once.

    The alternative is a finding against every row that could not be checked against
    it, which buries the one fact that explains all of them.
    """
    expected = [str(role) for role in (pack.setting("required_roles", []) or [])]
    if not expected:
        return
    # A role counts as present only if it produced records. A file that was detected
    # but blocked - a missing required column, say - leaves that source unusable, and
    # saying so once is more useful than leaving every dependent check unexplained.
    present = {read.detection.role for read in result.reads if read.records}
    if result.schedules:
        present.add("schedule")
    if not present:
        return  # nothing was read at all; the file-level flags already say so

    for role in expected:
        if role in present:
            continue
        context.flags.raise_flag(
            "SOURCE_MISSING",
            {
                "role": role,
                "consequence": _MISSING_CONSEQUENCE.get(role, "some checks cannot run."),
            },
            key_parts=(role,),
            node_id="intake",
        )


# ---------------------------------------------------------------------------
# Ledger, match, and rules
# ---------------------------------------------------------------------------


def _census_from(result: IngestResult) -> dict[tuple[str, date], int]:
    """Resident counts by facility and day, where a census was supplied."""
    import json

    census: dict[tuple[str, date], int] = {}
    for record in _records_for_role(result, "census"):
        payload = json.loads(record.get("payload_json") or "{}")
        facility = str(payload.get("facility") or payload.get("facility_code") or "")
        when = str(payload.get("date") or "")
        residents = payload.get("residents")
        if not facility or not when or residents in (None, ""):
            continue
        try:
            census[(facility, date.fromisoformat(when))] = int(float(residents))
        except ValueError:
            continue
    return census


def _build_ledger_and_match(
    context: RunContext, db: Database, result: IngestResult, pack: Pack
) -> None:
    """Claims, golden records, the four-way match, the staffing view, and the rules."""
    from sot.ledger.authority import authority_for_pack
    from sot.ledger.claims import claims_from_records, claims_from_segments
    from sot.ledger.golden import (
        build_credentials,
        build_pay_lines,
        conflict_findings,
        credential_holders,
        survive,
    )
    from sot.match.fourway import run_match
    from sot.rules.engine import RuleContext, load_rule_modules, run_rules
    from sot.views.staffing import build_daily_hours

    resolution = result.resolution
    if resolution is None:
        return

    roster = _records_for_role(result, "roster")
    payroll = _records_for_role(result, "payroll")
    credential_records = _records_for_role(result, "credentials")
    segments = _resolved_segments(db, context.run_id)
    result.segments = segments
    person_by_record = {link.record_id: link.person_id for link in resolution.links}
    for person in resolution.persons:
        if getattr(person, "record_id", ""):
            person_by_record.setdefault(person.record_id, person.person_id)

    authority = authority_for_pack(pack)
    display_names = {person.person_id: person.display_name for person in resolution.persons}

    with context.node("ledger", "Claims ledger", "ledger") as node:
        claims = [
            *claims_from_records(roster, source_role="roster", person_by_record=person_by_record),
            *claims_from_records(payroll, source_role="payroll", person_by_record=person_by_record),
            *claims_from_records(
                credential_records, source_role="credentials", person_by_record=person_by_record
            ),
            *claims_from_segments(segments),
        ]
        node.rows_in = len(roster) + len(payroll) + len(credential_records) + len(segments)
        node.rows_out = len(claims)

        golden = survive(claims, authority)
        holders = credential_holders([*roster, *credential_records], person_by_record)
        credentials = build_credentials(golden, holders, claims)
        pay_lines = build_pay_lines(payroll, person_by_record)

        result.golden = golden
        result.credentials = credentials
        result.pay_lines = pay_lines

        db.insert_rows("claims", [claim.as_row(context.run_id) for claim in claims])
        db.insert_rows(
            "golden_attributes", [value.as_row(context.run_id) for value in golden.values]
        )
        db.insert_rows("credentials", [item.as_row(context.run_id) for item in credentials])
        db.insert_rows("pay_lines", [line.as_row(context.run_id) for line in pay_lines])

        for finding in conflict_findings(
            golden, authority, display_names=display_names, credential_holders=holders
        ):
            _raise_finding(context, finding, "ledger")

    with context.node("match", "Four-way match", "match") as node:
        match = run_match(
            persons=resolution.persons,
            pay_lines=result.pay_lines,
            segments=segments,
            credentials=result.credentials,
            golden=result.golden,
            required_credential=pack.setting("required_credential", {}) or {},
            week_start=str(pack.setting("week_start", "monday")),
            tolerance=float(pack.setting("hours_tolerance", 0.25) or 0.25),
        )
        result.match = match
        node.rows_in = len(result.pay_lines) + len(segments)
        node.rows_out = len(match.weeks) + len(match.days)
        db.insert_rows("match_person_week", [week.as_row(context.run_id) for week in match.weeks])
        db.insert_rows("match_person_day", [day.as_row(context.run_id) for day in match.days])

    with context.node("staffing", "Staffing hours", "view") as node:
        pbj_codes = {}
        roles = pack.crosswalk("roles")
        if roles is not None:
            pbj_codes = {
                entry.code.upper(): entry.extra.get("pbj_code", "") for entry in roles.entries
            }
        staffing = build_daily_hours(
            segments=segments,
            match=result.match,
            pack=pack,
            display_names=display_names,
            pbj_codes=pbj_codes,
        )
        result.staffing = staffing
        node.rows_in = len(segments)
        node.rows_out = len(staffing.rows)
        db.insert_rows("daily_hours", [row.as_row(context.run_id) for row in staffing.rows])

    with context.node("views", "Views", "view") as node:
        from sot.views.expirations import build_expirations
        from sot.views.staffing import summarize

        facilities = {
            person.person_id: (getattr(person, "facility_code", "") or "")
            for person in resolution.persons
        }
        result.summaries = summarize(
            staffing=result.staffing, match=result.match, pack=pack, segments=segments
        )
        result.expirations = build_expirations(
            credentials=result.credentials,
            as_of=context.as_of,
            pack=pack,
            display_names=display_names,
            facilities=facilities,
            person_days=result.match.days,
            pay_lines=result.pay_lines,
            vendor_records=_records_for_role(result, "vendor_documents"),
        )
        node.rows_in = len(result.staffing.rows) + len(result.credentials)
        node.rows_out = len(result.summaries) + len(result.expirations.rows)

    with context.node("rules", "Rules", "rules") as node:
        load_rule_modules()
        rule_context = RuleContext(
            as_of=context.as_of,
            pack=pack,
            authority=authority,
            persons=resolution.persons,
            golden=result.golden,
            claims=claims,
            credentials=result.credentials,
            pay_lines=result.pay_lines,
            segments=segments,
            match=result.match,
            daily_hours=result.staffing,
            census=_census_from(result),
        )
        findings = run_rules(rule_context)
        node.rows_in = len(result.match.weeks) + len(result.match.days)
        node.rows_out = len(findings)
        for finding in findings:
            _raise_finding(context, finding, "rules")


def _resolved_segments(db: Database, run_id: str) -> list[dict[str, Any]]:
    """Shift segments with their resolved person, straight from the database."""
    return db.query("SELECT * FROM shift_segments WHERE run_id = ? ORDER BY segment_id", [run_id])


def _raise_finding(context: RunContext, finding: Any, node_id: str) -> None:
    evidence = []
    if finding.row_index or finding.page or finding.raw_value:
        evidence = [
            Evidence(
                row_index=finding.row_index,
                page=finding.page,
                column_name=finding.column,
                raw_value=finding.raw_value,
                bbox=finding.bbox,
            )
        ]
    context.flags.raise_flag(
        finding.code,
        dict(finding.params),
        entities=list(finding.entities),
        evidence=evidence,
        key_parts=finding.key_parts or (finding.code,),
        node_id=node_id,
    )
