# PROGRESS

Updated after each build phase. Format: done / next / risks.

---

## Phase 2 — Ingestion ✅

**Done**

- **Rule infrastructure.** All **81 rule codes** from spec section 13 declared as data in `sot/rules/catalog.py`, with severity, owner, priority, message template, and suggested action. 11 have evaluators so far; the rest are declared deliberately, so `docs/RULES.md` is complete and "which P0 rules are still missing" is a query rather than a memory exercise. Severity is a function where the spec says it varies.
- **Flag builder** with roll-up: informational findings aggregate per column, per file, or per run, keeping a count and up to five evidence pointers.
- **Pack contracts and crosswalks** for all five tabular healthcare sources, plus facilities, roles, and credential types. Synonyms are generous on purpose — they are the main defence against a file we have never seen.
- **Robust reader**: encoding ladder, content-based delimiter sniffing, header-position search, non-data row classification, field-count repair, null tokens, `.xlsx`.
- **Detection**: format from leading bytes, source from weighted header-signature similarity, with ties and low scores refused rather than guessed.
- **Header mapping**: learned decision → exact synonym → Jaro-Winkler, with ambiguity and missing-required reporting.
- **Immutable landing** by content hash, run context with per-step isolation, event log, CLI `ingest`, and report writer (`flags.csv`, `flags.json`, `summary.md`).
- **245 tests passing** (132 new), ruff clean.

**Verified, not assumed**

- `make verify-clean` passes: the clean set ingests with **nothing above INFO**, 48 records, zero quarantined.
- `make demo` on the messy set raises exactly the planted reader problem and nothing spurious.
- Ingesting the same files in a shuffled order produces byte-identical records and flags.
- Fourteen file-level chaos mutations pass as ordinary tests (M01–M09, M46, M47, M58, M69): renamed headers, reordered columns, an extra column, a dropped required column, an unquoted name, BOM + CRLF, Latin-1 accents, tab delimiters, junk rows, misleading filenames, a duplicate upload, an unrelated file, and a truncated row.
- An unrelated file blocks only itself; the four real sources still load.

**Six bugs found and fixed while building**

Four of these would have produced *plausible but wrong* output, which is the failure mode that matters here — nobody notices.

- Character-set detection reported **UTF-16 for a short Windows-1252 sample**, turning a surname into Chinese characters. Wide encodings now require a byte-order mark.
- Detection also reported **cp1250 for a Western European file**, which silently turns ñ into ń. Single-byte codepages differ only in which accented letters the high bytes mean, so a short sample cannot distinguish them; the assumed codepage is now explicit and configurable, and the fallback is always flagged.
- **Row repair accepted merges at any column**, so a row of three-letter codes rejoined as happily as a name and was silently corrupted. Repair is now restricted to columns the contract says hold a name.
- A **stray byte-order mark** survived a double-encoded file and renamed the first column, so its heading matched nothing.
- **`run_id` collided within the same second**, so re-running the same files — which is exactly what the rerun button does — hit a primary key violation. Now millisecond-resolved with a suffix fallback.
- **Duplicate detection depended on file order**: whichever copy arrived first was the one kept, so the flag named a different file run to run. Inputs are now canonically sorted before anything is read.

**Four deliberate deviations from the spec**, each recorded in `DECISIONS.md`

- Signature scoring weights required columns three times optional ones, rather than a flat share of columns matched.
- Stored header decisions are applied *before* the automatic strategies, not after.
- `FILE_DUPLICATE` fires for a repeat within one upload, not for re-ingesting the same file in a later run.
- Row numbers are physical 1-based lines, which matches a spreadsheet exactly and stays useful when a file has a preamble.

**Next — phase 3: normalizers and the PDF adapter**

Names, nicknames, dates, phones, credential numbers, hours, codes; then the schedule adapter with the shift grammar, footnote parsing, year inference, midnight split, and bounding-box capture.

**Risks**

- *New:* 50 P0 rules still have no evaluator. That is the plan — phases 3 and 5 are where they land — but it is the bulk of the remaining P0 work and the coverage report now tracks it.
- *Carried (R6):* "clean raises nothing above INFO" now holds for ingestion. It cannot be confirmed for the domain rules until phase 5.
- *Carried (R1):* the schedule PDF is next, and remains the highest-variance risk against the judges' real file.

---

## Phase 1 — Fixtures first ✅

**Done**

- `scripts/make_schedule_pdf.py`: parametric weekly-schedule PDF. The chaos deck can vary the dash character, the footnote, header wording, rows per page, grid lines, page splitting, and whether there is a text layer at all. Also rasterizes to an image-only PDF for the scanned case.
- `scripts/generate_samples.py`: the three healthcare sample sets, with every planted problem annotated with the rule code it should raise.
- `data/samples/healthcare/{clean,messy,scan}/` committed, plus a README documenting the construction and every planted trap.
- **113 tests passing** (34 new), ruff clean.

**Two design choices worth knowing**

- **Coverage first, payroll second.** The schedule is authored to satisfy the domain rules, and payroll is *derived* from it. Hand-written payroll that is hoped to reconcile is how fixtures drift; derived payroll reconciles by construction, so every variance in the messy set is a visible, deliberate override rather than an arithmetic slip.
- **The census is derived too.** Hours per resident per day is a ratio, so a census invented independently of the roster would put a compliant schedule in violation. The clean census is computed backwards from the thinnest staffed day, which keeps the clean set green when staffing is edited. The messy set ships a realistic, deliberately under-staffed census so the HPRD rule has something to find.

**Verified, not assumed**

- Byte-reproducible: generating twice into separate directories gives identical hashes for all 13 files, PDFs included (reportlab `invariant=1`). A test also asserts the committed fixtures are what the generator produces right now, so a stale fixture fails rather than drifts.
- The clean set is compliant *as data*, before the engine exists to judge it: RN coverage ≥ 8 consecutive hours on every facility-day, an aide on every facility-day, payroll reconciling exactly with the schedule per person per facility, every credential outside all four expiry windows, verifications fresh, aide certifications on month ends, and a census that satisfies all three HPRD minimums every day.
- The clean PDF extracts as a proper table through pdfplumber (ruled grid), day headers carry no year — so the year must be inferred from the payroll periods, exactly as the brief implies — and the scanned PDF yields zero text.
- A test reads the generator source and fails if it ever calls `date.today()` or similar: a fixture that moves with the calendar breaks tests on a date nobody chose.

**Three problems found and fixed during the phase**

- The messy payroll under-paid the one person given a shift the footnote does not define, because the generator looked hours up only in the footnote table. It now falls back to clock arithmetic, as the adapter will — otherwise the fixture carried an unintended hours variance on top of the intended one.
- The derived census oscillated between 3 and 6 across the week, tracking the rota rather than reality. Now one number per facility, taken from the thinnest day.
- A fixture first name was changed from "Grace" to "Astrid": the no-hard-coding guard watches every fixture name, and "grace period" is a phrase credential-expiry code will legitimately want to use.

**Next — phase 2: ingestion**

Content-based detection, immutable landing by sha256, the robust reader (encoding ladder, delimiter sniff, header-position search, row repair), contracts, header mapping, quarantine.

**Risks**

- *Cleared:* reportlab 5.0.1 works and supports `invariant`, so PDFs are byte-reproducible.
- *New:* the clean census works out at 3 residents per facility. That is the largest census ten staff can serve while meeting all three HPRD minimums on the thinnest day — arithmetic, not a typo, and the README says so. If it reads as implausible at judging, the fix is more staff in the fixture, not a looser rule.
- *Carried (R6):* the clean set is compliant as data, but "raises nothing above INFO" cannot be confirmed until the rules exist. `make verify-clean` is the gate.
- *Carried (R1):* schedule-PDF extraction against the judges' real file is still the highest-variance risk. The parametric generator is the mitigation — it can synthesize layouts I have not seen.

---

## Phase 0 — Scaffold ✅

**Done**

- `git init` (local only, no remote), repository layout per spec section 4, `.gitignore` excluding `var/` and `reports/`.
- `pyproject.toml` with **exact pins** for all 14 runtime dependencies plus `requirements.lock` from the resolved environment. `uv` is absent on this machine, so `make setup` uses venv + pip, as the spec allows.
- `Makefile`: `setup dev api web samples demo verify-clean test chaos lint fmt docs reset`, self-documenting via `make help`.
- DuckDB schema (`sot/store/schema.sql`, 25 objects) covering every table in spec section 18, plus `run_files`.
- `sot/store/db.py`: single-writer connection, idempotent schema, ragged-dict inserts, `delete_run`, `truncate_all`.
- Foundation modules carrying the determinism decisions: `canon.py` (canonical JSON, cross-type sorting, order-free hour sums), `ids.py` (blake2b identifiers), `tri.py` (Kleene three-valued logic), `config.py` (env-overridable paths).
- FastAPI app with `/api/health` and `/api/packs`, CORS limited to localhost, and a catch-all exception handler so an unexpected error is still JSON.
- CLI skeleton (`python -m sot`) with the full `ingest` argument surface parsed; `health` works today.
- Vite + React 19 + TypeScript (**strict**, plus `noUncheckedIndexedAccess`) + Tailwind v4, routed shell with all nine nav destinations and the header strip. Dev server proxies `/api` to :8000.
- Pack manifests for `healthcare_ny` and `trucking`, every regulatory threshold annotated with its source URL (pulled forward from phase 2 so pack discovery is real rather than stubbed).
- **79 tests passing**, ruff clean, frontend builds.

**Verified, not assumed**

- `make dev` → web 200, API 200, and `/api/health` 200 *through the Vite proxy*.
- Identifiers are stable across processes with deliberately different `PYTHONHASHSEED` values — the test spawns two subprocesses and compares.
- `delete_run` clears derived rows while leaving `files` and `decisions` intact.

**Next — phase 1: fixtures first**

Deterministic `scripts/generate_samples.py --seed 42`, parametric `make_schedule_pdf.py`, and the clean / messy / scan sample sets.

**Risks**

- *New:* Vite 8 binds IPv6 localhost only, so `http://127.0.0.1:5173` does not answer. `http://localhost:5173` does. Documented in the README; not worth fighting Node's DNS ordering over.
- *New:* `reportlab` resolved to 5.0.1, a major version newer than most published examples. Phase 1 exercises it first; if the API has moved, that surfaces immediately rather than at demo time.
- *Carried (R6):* the clean set must raise nothing above INFO, but that cannot be checked until the rules exist in phase 5. `make verify-clean` is already wired as the gate.
- *Carried (R1):* schedule-PDF extraction against the judges' real file remains the highest-variance risk.
