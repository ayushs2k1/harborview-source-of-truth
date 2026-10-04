"""Working out what a file is from its contents.

Filenames lie. ``Book1.xlsx``, ``export (3).csv`` and ``FINAL_v2_USE_THIS.csv`` are all
real, and none of them says what is inside. So the format comes from the leading bytes
and the source type comes from how well the column headings match each contract's
signature.

The header is also searched for rather than assumed to be the first line, because
exports routinely begin with a title row, a date stamp, or a blank. Both questions -
where does the table start, and what kind of table is it - are answered in the same
pass, since neither can be settled without the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sot.ingest.contracts import Contract, Pack
from sot.ingest.headers import HeaderMapping, map_headers

#: Leading bytes that identify a format.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"

MEDIA_PDF = "pdf"
MEDIA_TABULAR = "tabular"
MEDIA_UNKNOWN = "unknown"

METHOD_SIGNATURE = "header_signature"
METHOD_PDF = "pdf"
METHOD_OVERRIDE = "override"
METHOD_NONE = "none"


def detect_media_kind(data: bytes, filename: str = "") -> str:
    """Format from content, falling back to the extension only for empty files."""
    if data.startswith(_PDF_MAGIC):
        return MEDIA_PDF
    if data.startswith(_ZIP_MAGIC):
        return MEDIA_TABULAR if _looks_like_xlsx(data) else MEDIA_UNKNOWN
    if not data.strip():
        # Nothing to go on. The extension is a guess, and an empty file will fail
        # classification anyway; this just makes the flag say something sensible.
        return (
            MEDIA_TABULAR if filename.lower().endswith((".csv", ".tsv", ".txt")) else MEDIA_UNKNOWN
        )
    return MEDIA_TABULAR


def is_xlsx(data: bytes) -> bool:
    """True for an Office Open XML workbook."""
    return data.startswith(_ZIP_MAGIC) and _looks_like_xlsx(data)


def _looks_like_xlsx(data: bytes) -> bool:
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    return "xl/workbook.xml" in names


@dataclass
class Detection:
    """What a file turned out to be, and how confident we are."""

    media_kind: str
    source: str | None = None
    role: str | None = None
    score: float = 0.0
    margin: float = 0.0
    header_row_index: int | None = None
    mapping: HeaderMapping | None = None
    method: str = METHOD_NONE
    #: Every contract's best score, for the flag message and the UI.
    scores: dict[str, float] = field(default_factory=dict)
    runner_up: str | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.source is not None

    def best_alternatives(self, limit: int = 3) -> list[tuple[str, float]]:
        return sorted(self.scores.items(), key=lambda item: (-item[1], item[0]))[:limit]


def classify_grid(
    rows: list[list[str]],
    pack: Pack,
    *,
    override: str | None = None,
    learned_headers: dict[str, dict[str, str]] | None = None,
) -> Detection:
    """Find the header row and decide which source this is.

    Every candidate header row is scored against every contract, and the best pair
    wins. A score below the pack's threshold, or two contracts too close together, is
    reported as unknown rather than guessed at: a payroll file silently read as a
    roster would be worse than one that refuses to load.
    """
    min_score = float(pack.setting("detection.min_score", 0.5))
    min_margin = float(pack.setting("detection.min_margin", 0.15))
    similarity = float(pack.setting("detection.header_similarity", 0.90))
    max_preamble = int(pack.setting("detection.max_preamble_rows", 20))
    learned_headers = learned_headers or {}

    contracts = list(pack.contracts)
    if override:
        contract = pack.contract(override)
        if contract is None:
            return Detection(
                MEDIA_TABULAR,
                method=METHOD_NONE,
                reason=f"override names source {override!r}, which this pack does not define",
            )
        contracts = [contract]

    best_per_contract: dict[str, tuple[float, int, HeaderMapping]] = {}
    for row_index, row in enumerate(rows[: max_preamble + 1]):
        if sum(1 for cell in row if str(cell).strip()) < 2:
            continue  # a title or a stray cell, not a header row
        for contract in contracts:
            mapping = map_headers(
                row,
                contract,
                similarity=similarity,
                learned=learned_headers.get(contract.source, {}),
            )
            current = best_per_contract.get(contract.source)
            if current is None or mapping.score > current[0]:
                best_per_contract[contract.source] = (mapping.score, row_index, mapping)

    scores = {source: value[0] for source, value in best_per_contract.items()}
    if not scores:
        return Detection(
            MEDIA_TABULAR,
            method=METHOD_NONE,
            scores=scores,
            reason="no row in the first rows of the file looks like a header",
        )

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_source, best_score = ranked[0]
    runner_up, runner_score = ranked[1] if len(ranked) > 1 else (None, 0.0)
    margin = best_score - runner_score
    _, header_row_index, mapping = best_per_contract[best_source]
    contract = next(c for c in contracts if c.source == best_source)

    if override:
        return Detection(
            MEDIA_TABULAR,
            source=best_source,
            role=contract.role,
            score=best_score,
            margin=1.0,
            header_row_index=header_row_index,
            mapping=mapping,
            method=METHOD_OVERRIDE,
            scores=scores,
            reason="source type was set by hand",
        )

    if best_score < min_score:
        return Detection(
            MEDIA_TABULAR,
            score=best_score,
            margin=margin,
            scores=scores,
            runner_up=best_source,
            method=METHOD_NONE,
            reason=f"best match {best_source} scored {best_score:.0%}, below the "
            f"{min_score:.0%} threshold",
        )

    if runner_up is not None and margin < min_margin:
        return Detection(
            MEDIA_TABULAR,
            score=best_score,
            margin=margin,
            scores=scores,
            runner_up=best_source,
            method=METHOD_NONE,
            reason=f"{best_source} ({best_score:.0%}) and {runner_up} ({runner_score:.0%}) "
            "match about equally well",
        )

    return Detection(
        MEDIA_TABULAR,
        source=best_source,
        role=contract.role,
        score=best_score,
        margin=margin,
        header_row_index=header_row_index,
        mapping=mapping,
        method=METHOD_SIGNATURE,
        scores=scores,
        runner_up=runner_up,
        reason=f"matched the {best_source} signature at {best_score:.0%}",
    )


def schedule_contract(pack: Pack) -> Contract | None:
    """The pack's schedule source, if it declares one. PDFs are routed here."""
    contracts = pack.contracts_for_role("schedule")
    return contracts[0] if contracts else None
