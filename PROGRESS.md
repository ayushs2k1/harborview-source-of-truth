# PROGRESS

Updated after each build phase. Format: done / next / risks.

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
