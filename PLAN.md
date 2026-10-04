# PLAN: Harborview Source of Truth

Status: **awaiting approval**. No code written yet.
Written against `SPEC.md` (read in full). Target: P0 (phases 0–7) solid, P1 (8–10) next, P2 (11) only if time remains.

---

## 1. Environment check (verified just now, not assumed)

| Thing | Found | Consequence |
|---|---|---|
| Python | 3.12.2 | Meets the 3.11+ floor. |
| `uv` | **not installed** | Use `python3 -m venv .venv` + pip, as the spec allows. `make setup` creates `.venv`, installs from pinned `pyproject.toml`, writes `requirements.lock` (`pip freeze`) so re-installs are reproducible. |
| Node / npm | v25.1.0 / 11.6.2 | Fine for Vite 6/7. |
| git | 2.45.2, but **this directory is not a repo** | Section 26 says commit after each phase → I need `git init` here (see Q1). |
| tesseract | **not installed** | OCR (P2) is unavailable. Scanned PDFs take the spec'd `PDF_NO_TEXT_LAYER` BLOCKER path, which M45 explicitly permits ("OCR used, **or** `PDF_NO_TEXT_LAYER`; never a crash"). See Q3. |
| PyPI / npm registry | both reachable | I can resolve and pin exact versions at phase 0 rather than guessing them in this plan. |

---

## 2. Design decisions I am committing to

These are the things the spec leaves to me. They are the ones most likely to bite later, so I want them agreed up front. All go into `DECISIONS.md`.

**D1 — Hashing.** Every stable ID (`flag_id`, provisional `person_id`, record fingerprints) is `blake2b(canonical_json(payload), digest_size=8)`. Never Python's `hash()`, which is salted per process and would break stability across runs.

**D2 — `run_id` is excluded from every content hash.** `run_id` is `R-<utc-ts>-<4 hex of the input digest>`. Determinism tests compare run outputs with `run_id`, timestamps and durations stripped. `flag_id` already excludes it by spec.

**D3 — Order independence is enforced at the boundary, not hoped for.** Inputs are canonically sorted before processing: files by `(source_type, sha256)`, rows by `(file_sha, row_index)`, PDF cells by `(page, row, col)`. No `set` or `dict` iteration ever reaches an output; everything goes through `sorted()` with an explicit key. A test ingests the demo set in several shuffled file orders and asserts byte-identical canonical output.

**D4 — Provisional person IDs are cluster-canonical, not first-seen.** The spec says "hash of the first record's" fields, which is order-dependent. I will hash the **lexicographically smallest** `(name_key, role, facility)` in the cluster instead, so the ID is identical regardless of file order. Same intent, deterministic.

**D5 — Three-valued logic is a real type.** A `Tri` enum (`PASS`/`FAIL`/`UNKNOWN`) with Kleene `and`/`or`. The UI renders `UNKNOWN` as its own state, never green — principle 6 enforced in one place rather than per rule.

**D6 — Severity is a function, not a constant.** The rule registry stores `severity(ctx) -> Severity`. Needed by `UNMATCHED_SCHEDULE`, `HOURS_EXCESSIVE_WEEK`, `CREDENTIAL_EXPIRING` (90/60/30/14 bands), `CREDENTIAL_EXPIRED`, `LICENSE_NOT_IN_SERVICE`, `HOURS_VARIANCE` (INFO when explained by PTO), `PDF_NO_TEXT_LAYER`, `PDF_FACILITY_UNKNOWN`, `ZERO_RN_DAYS_QUARTER`. Constants are just the degenerate case.

**D7 — INFO aggregation is declared in the registry.** Each code carries `aggregate: none | by_column | by_file | by_run`. The flag builder rolls those up into one flag with a count and ≤5 sample evidence pointers, so the inbox never floods.

**D8 — Typed ports with load-time validation.** Port types `RawTable / StdTable / Links / Claims / Golden / MatchTables / Flags / View`. `pipeline.yaml` is validated on load: unknown node type, type-mismatched edge, or cycle is a hard config error with a readable message — before any data moves.

**D9 — Degradation is explicit.** Every node result carries `status ∈ {ok, degraded, failed}` plus `missing_inputs`. A failed node becomes a BLOCKER flag; downstream nodes run with what exists, inherit `degraded`, and rules whose inputs are missing return `UNKNOWN` rather than `FAIL`. A missing payroll file must never manufacture `SCHEDULED_NOT_PAID` for everyone.

**D10 — Numbers.** Hours are floats rounded to 4 dp at every boundary, summed in sorted order, rounded once at display. All equality goes through a tolerance helper seeded from `hours_tolerance`.

**D11 — One DuckDB writer.** A single owning module holds the connection; the API serializes runs behind an asyncio lock and executes ingestion in a worker thread so the SSE stream stays responsive.

**D12 — The shift-segment producer is source-agnostic.** The PDF adapter and a tabular dispatch adapter both emit the same `shift_segments` contract. This is what lets trucking's `dispatch.csv` reuse the engine with zero core changes (section 22's stated goal) instead of being special-cased.

**D13 — PDF evidence.** Pages are rasterized once per file with pypdfium2 to `var/pages/<file_id>/<page>.png` at a fixed DPI; bboxes are stored in PDF points **plus** the render scale, so the UI maps to pixels without re-deriving anything.

**D14 — The generator is validated by the engine.** Phase 1 writes fixtures before the engine exists, so "the clean set is green at the pinned as-of" can't be checked until phase 5. I will add a `make verify-clean` gate then, and tune generator parameters (RN count and coverage pattern, census figures) until the clean set yields nothing above INFO. Flagged as a risk (R6) because it's a real sequencing dependency.

**D15 — A test enforces "never hard-code the samples."** `tests/test_no_hardcoded_samples.py` greps `sot/**` for a denylist (facility names and codes, sample employee/payroll/license IDs, the sample dates, "Harborview") and fails on any hit. `packs/`, `scripts/`, `data/` and `tests/` are exempt — the crosswalk seeds and the generator are *supposed* to contain them. This makes your constraint mechanically checkable rather than a matter of my discipline.

---

## 3. Phases

Effort is relative size, not a schedule. Cut order if time runs short: 11 → 10 → parts of 8. Never P0 robustness or the chaos core.

### Phase 0 — Scaffold (S)
Repo layout, `git init`, `pyproject.toml` with pinned deps, `Makefile` (`setup dev demo test chaos lint reset docs verify-clean`), `.gitignore` (`var/`, `reports/`, `.venv/`, `node_modules/`), DuckDB schema, FastAPI app with `/api/health`, Vite + React + TS + Tailwind shell with `/api` proxy, pytest wired.
**Exit:** `make setup && make dev` serves API on :8000 and UI on :5173; `make test` runs green.

### Phase 1 — Fixtures first (M)
`scripts/generate_samples.py --seed 42` (deterministic) and `scripts/make_schedule_pdf.py` (parametric: header text, footnote on/off, cell values, dash style, rows per page, scanned or not — the chaos deck mutates it). Produces `clean/`, `messy/` (every planted problem in §21), `scan/`, plus optional `census.csv` and `vendor_documents.csv`. Tricky names included (José Peña, Ana García-López, Kevin O'Brien, Robert Hayes Jr., Kate/Katherine, one cross-facility float).
**Exit:** files exist and are byte-stable across two runs with the same seed; the PDF visibly matches the described layout.

### Phase 2 — Ingestion (M)
Content-based format detection, immutable landing by sha256, header-signature classification (>0.5 wins; ties → `FILE_TYPE_UNKNOWN`), the robust reader (encoding ladder, delimiter sniff, header-position search, non-data row dropping, delimiter repair, null tokens, raw-value retention), contract loading, header mapping (exact synonym → Jaro-Winkler ≥0.90 → learned `HEADER_MAP`), quarantine.
**Exit:** clean set ingests with zero BLOCKER/WARNING; messy set produces exactly the expected file/format flags; reader-quirk unit tests pass (M01–M09, M46, M47, M58, M69).

### Phase 3 — Normalizers + PDF adapter (L)
Names (orders, particles, suffixes, credentials, accents), nicknames (~200 bidirectional pairs incl. Spanish), dates (serials, ambiguity, impossible, 2-digit pivot), phones, license numbers (O/0, I/L/1 confusion, prefix inference), hours, codes via crosswalks. Then the PDF adapter: three-tier extraction (lines table → text table → word clustering off header anchors), facility matching with majority-inference fallback, day-header parsing with the 3-step year inference and Dec→Jan rollover, footnote parsing, wrapped-cell merging, the shared shift grammar, non-work codes, per-segment hours with footnote authority, bbox capture.
**Exit:** clean PDF parses to exactly the expected segments; ≥40 shift-grammar unit tests; date/phone/name/license suites pass.

### Phase 4 — Identity resolution (M)
Decisions applied first, deterministic license-number anchor, then weighted scoring (the spec's feature/weight table, in pack config), bands, ambiguity check, greedy one-to-one with deterministic tie-breaks, provisional persons for unmatched, duplicate/collision checks, and a stored explanation per link (features, levels, values compared, weights, total, band, `decided_by`) for the waterfall UI.
**Exit:** every clean record links correctly; look-alike and ghost cases raise the expected flags; the 60-person seeded ground-truth set hits precision ≥0.98 on auto-links.

### Phase 5 — Ledger, golden records, four-way match, rules (L — the biggest)
Claims with full locators, survivorship from `authority.yaml` (source order → `observed_on` recency → completeness, storing the winning `claim_id` and the rule used), conflict retention, full rebuild per run. Person-week and person-day tables, primary status, tolerance, PTO explanation, coverage-first comparison. Then the rule registry and all P0 rules across file/format/identity/cross-source/time/PDF/domain, with the flag builder (stable IDs, plain-English messages built from data, evidence pointers, suggested action, owner role).
**Exit:** messy set yields the expected flags with correct severities and messages; clean set at as-of 2026-09-21 yields nothing above INFO (`make verify-clean`).

### Phase 6 — Views, API, CLI (M)
`daily_hours` with midnight split, meal deduction and tiering; facility/period/quarter summaries with PBJ quarter labels and due dates; expiration radar incl. CNA recert evidence; referral readiness with the YES/NO/UNKNOWN verdict. Full API surface from §19, SSE events, CSV exports, CLI writing `reports/<run_id>/{flags.csv, flags.json, pbj_daily_hours.csv, expirations.csv, referral_readiness.csv, summary.md}`, exit 0 on bad data.
**Exit:** exports are correct for the fixtures; CLI never exits non-zero on messy input.

### Phase 7 — Frontend P0 (L)
Ingest (drag-drop, detected type + confidence, override, as-of, pack), Pipeline (React Flow + dagre, custom node cards, animated edges, SSE, node drawer with samples/flags/params/re-run, "Replay last run"), Flags (severity tabs, filters, cards, evidence viewer with CSV cell and PDF bbox highlight, INFO aggregates), People (table, evidence graph, score waterfall, attribute table, credentials, shift grid), and the three views.
**Exit:** the whole demo runs end to end in the browser at 1280px.

### Phase 8 — Decisions loop (M) · P1
Accept/reject match, code map, header map, dismiss with reason, notes; fingerprint-based storage; export/import `var/decisions.yaml`; audit log; safe parameter edits validated against a JSON schema into `var/overrides.yaml`; re-run.
**Exit:** resolving a flag and re-running makes it disappear, and the audit log says why.

### Phase 9 — Chaos deck (M) · P1
All ~60 mutations as `{id, description, targets, mutate, expect_codes, forbid_codes}` against the clean baseline; `make chaos` writes `reports/chaos_coverage.md` + `.json`; the Chaos page renders the JSON.
**Exit:** every P0 code is exercised by ≥1 mutation and the uncovered list is empty; every mutation finishes without an exception.

### Phase 10 — Trucking pack + docs (M) · P1
`packs/trucking/` (contracts, crosswalks, authority, rules, pipeline), its fixtures incl. `dispatch.csv` through the tabular shift-segment adapter (D12), live pack switching. `README.md` with a Mermaid architecture diagram, `DECISIONS.md`, `docs/DEMO.md`, generated `docs/RULES.md`.
**Exit:** the pack swap works live and only the source and rule nodes differ.

### Phase 11 — Stretch (—) · P2
OCR fallback (needs tesseract), optional LLM assist behind a key and off by default, run-to-run diff, source quality scorecards.

---

## 4. Files I will create

**Engine (`sot/`)** — `cli.py`, `config.py`, `ids.py` (D1), `tri.py` (D5), `canon.py` (sorting/canonical JSON, D3).
- `pipeline/`: `spec.py` (load + validate + typed ports), `executor.py` (topo run, try/except, degradation), `events.py`, `stats.py`
- `ingest/`: `detect.py`, `landing.py`, `reader.py` (encoding/delimiter/header/row repair), `contracts.py`, `headers.py`, `quarantine.py`
- `adapters/`: `schedule_pdf.py`, `dispatch_table.py` (D12), `base.py`
- `normalize/`: `names.py`, `nicknames.py`, `dates.py`, `phones.py`, `ids_licenses.py`, `hours.py`, `shifts.py` (shared grammar), `codes.py`
- `resolve/`: `candidates.py`, `features.py`, `scoring.py`, `assign.py`, `explain.py`
- `ledger/`: `claims.py`, `authority.py`, `survivorship.py`, `golden.py`
- `match/`: `person_week.py`, `person_day.py`, `fourway.py`
- `rules/`: `registry.py`, `builder.py`, `severity.py`, and rule modules `file_rules.py`, `format_rules.py`, `identity_rules.py`, `cross_source_rules.py`, `time_rules.py`, `pdf_rules.py`, `domain_healthcare.py`, `domain_trucking.py`
- `views/`: `staffing.py` (PBJ, midnight split, meal, tiers), `expirations.py`, `referral.py`, `exports.py`
- `decisions/`: `store.py`, `fingerprint.py`, `apply.py`, `audit.py`
- `store/`: `schema.sql`, `db.py`, `queries.py`, `migrate.py`
- `assist/`: `__init__.py` stub, off by default
- `api/`: `app.py`, `deps.py`, `sse.py`, `routers/{ingest,runs,pipeline,flags,decisions,persons,evidence,views,exports,chaos,packs,health}.py`

**Packs** — `packs/core/nicknames.csv` + shared defaults; `packs/healthcare_ny/{pack.yaml, pipeline.yaml, authority.yaml, rules.yaml, contracts/{hr,payroll,licenses,schedule_pdf,census,vendor_documents}.yaml, crosswalks/{facilities,roles,credential_types}.csv}`; `packs/trucking/` in the same shape.

**Web (`web/`)** — Vite config with the `/api` proxy, Tailwind, `src/api/client.ts`, `src/hooks/useSSE.ts`, `src/components/` (severity chip, evidence viewer, score waterfall, KPI tile, data table, drawer), `src/pages/` (Ingest, Pipeline, Flags, People, PersonDetail, Staffing, Expirations, Referrals, Chaos, Settings), `src/flow/` (node cards, dagre layout).

**Scripts** — `generate_samples.py`, `make_schedule_pdf.py`, `gen_rules_doc.py`, `gen_identity_benchmark.py`.

**Tests** — `tests/unit/` (one module per normalizer, reader quirks, shift grammar, scoring, survivorship, rules), `tests/integration/` (clean green, messy expected-flags, determinism under shuffled order, API smoke, CLI smoke), `tests/chaos/` (deck + runner + coverage report), `tests/test_no_hardcoded_samples.py` (D15).

**Docs** — `PROGRESS.md`, `DECISIONS.md`, `README.md`, `docs/DEMO.md`, `docs/RULES.md` (generated).

---

## 5. Libraries

Exactly the spec's list; nothing extra. Versions get pinned to whatever resolves at phase 0 and frozen into `requirements.lock` (both registries are reachable, so these are real pins, not guesses).

**Backend:** fastapi, uvicorn[standard], duckdb, pydantic v2, pyyaml, rapidfuzz, jellyfish, pdfplumber, pypdfium2, reportlab, charset-normalizer, openpyxl, python-multipart, sse-starlette.
**Dev:** pytest, httpx, ruff. (Hypothesis only if a normalizer actually wants it; it's optional in the spec.)
**Optional, off by default:** pytesseract + Pillow, anthropic.
**Frontend:** react, react-dom, typescript, vite, @xyflow/react, @dagrejs/dagre, react-router-dom, tailwindcss.

No Dagster/Airflow/n8n/Node-RED — the DAG executor is ~150 lines in `pipeline/executor.py`. Any addition beyond this list gets justified in `DECISIONS.md`.

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **The judges' PDF doesn't parse.** Their real schedule may differ in layout, fonts, or table ruling. Highest-variance single point of failure. | Three independent extraction tiers, anchor-based column inference rather than fixed positions, page-level BLOCKER isolation so one bad page never kills the run, and 12 PDF mutations in the chaos deck. The parametric generator lets me synthesize layouts I haven't seen. |
| R2 | **Unknown columns/aliases in their files.** Synonym lists are guesses about someone else's export. | Fuzzy header matching, `HEADER_UNMAPPED_COLUMN` keeps the data as `extra.*` claims rather than dropping it, one-click `HEADER_MAP` in the UI, and `--type` override in the CLI. Nothing is silently lost. |
| R3 | **Scope.** ~70 rule codes, 10 screens, 2 packs, 60 chaos mutations. | Table-driven registry and shared helpers keep per-rule cost low; strict P0→P1→P2 ordering; the documented cut list. |
| R4 | **Determinism bugs** from dict/set ordering, float accumulation, or salted hashing — these hide until a judge re-runs and gets different numbers. | D1/D3/D10 plus a shuffled-order integration test that fails loudly. |
| R5 | **Match thresholds tuned to my fixtures** and wrong on real data. | Weights live in pack config, not code; the 60-person ground-truth benchmark measures precision/recall; the review band exists precisely so borderline cases become human decisions rather than silent errors. |
| R6 | **Clean-set greenness can't be verified until phase 5** (D14), so phase 1 fixture choices may need rework — particularly RN coverage every facility-day and census numbers that satisfy 3.5/1.1/2.2 HPRD. | Generate coverage-first (lay down RN coverage, then derive payroll from the schedule), keep generator parameters in one config block, and add `make verify-clean` to `make test` the moment rules exist. |
| R7 | **Domain facts challenged by judges.** Every NY/PBJ number is a factual claim I'm making on your behalf. | Each threshold sits in `pack.yaml` with its source URL in a comment, editable in Settings, and surfaced in the UI as an assumption (e.g. the meal-deduction effect on reported hours). Nothing is buried in code. |
| R8 | **OCR unavailable** (no tesseract). | Spec-sanctioned BLOCKER path; M45 passes either way; documented as an optional install. |
| R9 | **Demo-day failure.** | "Replay last run" serves stored events with no recompute, plus the CLI as a second path that needs no browser. |

---

## 7. Open questions

Defaults are what I'll do if you say nothing; only Q1 actually blocks me.

**Q1 — Git.** This directory isn't a repo, but §26 tells me to commit after each phase. **Default: `git init` here and commit locally after each phase. No remote, no push.** Say the word if you'd rather I didn't create a repo, or want it initialized somewhere else.

**Q2 — LLM assist (phase 11).** It's P2, needs an API key, and cuts against the offline principle unless opt-in. **Default: scaffold the settings toggle, build nothing behind it unless time clearly remains.**

**Q3 — OCR.** tesseract isn't installed. **Default: ship the BLOCKER path and document `brew install tesseract` as optional.** Alternative: `make setup` offers to install it.

**Q4 — PBJ job-title codes.** The spec says to verify them against CMS's current list; I can't do that authoritatively from here. **Default: ship the spec's table in pack config with source comments and make it editable**, rather than silently presenting unverified codes as fact.

**Q5 — Trucking depth.** **Default: full pack config + generated fixtures + live switching, but the chaos deck stays healthcare-only** (the deck is where the remaining time is better spent). Say if you want trucking mutations too.

---

## 8. What I'll do on approval

Start phase 0, keep `make test` green, update `PROGRESS.md` (done / next / risks) and commit at the end of each phase, and derive everything from the data and pack config — nothing from the sample records hard-coded into `sot/`, with D15 enforcing it.
