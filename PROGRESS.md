# PROGRESS

Updated after each build phase. Format: done / next / risks.

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
