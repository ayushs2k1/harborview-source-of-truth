# PROGRESS

Updated after each build phase. Format: done / next / risks.

---

## Phases 7–9 — Front end, decisions loop, chaos deck ✅

**Phase 7 — the front end**

Nine screens, strict TypeScript, no UI kit.

- **Ingest**: drag and drop, detected type per file, as-of date and pack, recent runs.
- **Pipeline**: a React Flow canvas laid out with dagre from `/api/pipeline`. Node cards show rows in and out, rows held back, and flag counts by severity; edges animate while the run streams in over SSE and carry row counts. Clicking a step opens a drawer with its ports, its last-run numbers, and any error. "Replay last run" re-streams the stored log with nothing recomputed.
- **Flags**: severity tabs with counts, category filter, cards with entity chips, and an evidence viewer that shows the source row with the column highlighted or the rendered PDF page with the bounding box drawn on it.
- **People**: the roster with credential and finding counts, and a person page with the **evidence graph** — the person in the middle, every source record around them, each edge carrying the score that attached it. Clicking an edge opens the feature waterfall.
- **Staffing, Expirations, Referrals**: the three client problems, each with its assumptions visible.
- **Settings**: the 14 editable parameters with their ranges and shipped defaults, plus the decision log.

**Phase 8 — the decisions loop**

Decisions are recorded from the flag drawer, listed in Settings with their audit trail, and applied at the start of the next run. "Re-run with current decisions" is on the Pipeline page. Parameter edits are validated and written as overrides, so the pack's shipped values stay visible and one reset undoes everything.

**Phase 9 — the chaos deck**

**62 mutations, all passing. 58 of 58 P0 rules exercised.** Each breaks the clean sample in one specific way and asserts two things: what must be raised, and what must *not* be. The second half is the one that catches over-reaction — a system that panics about a renamed column header is as useless as one that misses a ghost employee.

**Four real bugs the deck found**

- **Two findings could share a flag id**, and the second was lost to a primary key violation. Content-based ids are what let a finding keep its identity between runs; the cost is that two code paths can reach the same identity within one run. They are now merged, which is the honest reading — that is the same finding said twice.
- **The footnote parser read the whole page**, so shift tokens in the table above were swept into it and a 12-hour shift was priced at 8. It now reads only below the table.
- **Two roster rows sharing an employee number** crashed the identity step on a duplicate key. The collision is itself a finding; the table now holds the first rather than neither.
- **A blocked file still counted its source as present**, so a payroll export missing its hours column never reported the source as unusable.

**Verified end to end** through a live server: upload the messy set, watch the run, and every endpoint the UI needs answers — 14 critical and 15 warning findings, person graphs with scored edges, all three views, and the exports.

---

## Phase 6 — Views, API, and CLI ✅

**Done**

- **Expiration radar**: every credential and vendor document in one list sorted by urgency, with what a date alone cannot tell you — whether anybody worked on the wrong side of it, and whether the renewal can be supported by the hours we hold.
- **Referral readiness**: RN coverage as an unbroken stretch, licensed and aide hours, tour cover, on-duty staff with credential status, open critical findings for that facility-day, and hours per resident before and after one more admission. Labelled a fast indicator, with the note that the statutory standard is a quarterly average.
- **Staffing summaries** per facility and period, with the filing period named: `FFY2026 Q4 (Jul–Sep), due Nov 14, 2026`. Federal fiscal quarters, not calendar ones.
- **The pipeline specification**: a validated graph with typed ports. It refused my own first draft — the views step consumed census data it had not declared — which is the point of validating before any data moves.
- **26 API endpoints**, including live SSE while a run happens and replay from the stored log afterwards.
- **Safe parameter editing**: 14 declared parameters with types and ranges, written to an overrides file so the pack's shipped defaults stay visible and one deletion undoes everything.
- **Six CLI reports** per run, plus eight CSV exports over the API.
- **709 tests passing** (43 new), ruff clean.

**Two bugs the tests caught**

- The referral view read the adapter's own segments, which have no person attached because resolution had not run when they were made. Everybody's credential status came back unknown.
- Rebuilding person-days from storage dropped the three-valued columns, so the API reported every credential as unknown while the direct call reported them correctly. Unknown is never green, so the view said it could not tell — which is the one wrong answer that looks responsible.

**Next — phases 7 to 9**

---

## Phase 5 — Ledger, golden records, the four-way match, and the rules ✅

**Done**

- **The claims ledger.** Every value every source gave us, stored with the file, row and column it came from and the date the source vouches for it. 227 claims from the clean set, nothing merged on the way in.
- **Survivorship** from `authority.yaml`: source order, then the later observation, then completeness, then a stable hash. The winning claim records *which step decided it*, and the losing claims stay beside it.
- **The four-way match** at two grains. The person-week is where money reconciles; the person-day is where compliance lives. Coverage is established before anything is compared.
- **The staffing view**: midnight split, meal deduction, and a tier on every figure saying how far it is corroborated.
- **Thirty-one rule evaluators**, registered against the codes they raise.
- **81 of 82 rules now have evaluators**, up from 49. **Every P0 rule is live**; only `VOLUME_DROP` (P2, needs run history) remains.
- **666 tests passing** (103 new), ruff clean.

**Both exit criteria met**

- The clean set at the pinned as-of date raises **nothing above INFO**, and every one of its eleven person-weeks is `MATCHED`.
- The messy set raises **30 findings above INFO** — 14 critical, 16 warnings — each with the right severity, and each traceable to a planted problem. Tested individually, by code and by severity.

**Rule coverage is now derived, not declared**

Evaluators register against the codes they emit, so "which P0 rules are still missing" is computed from the code rather than from a flag somebody has to remember to flip. Only rules raised inline while reading a file still carry a manual marker, because they have nowhere to register.

**Three findings worth recording**

- **A legitimate float was reported as a facility conflict**, which broke the clean set. Comparing the golden home, paid and worked facility collapses somebody who works at two sites into one value per attribute and then reports the difference as a disagreement — exactly backwards, since floats are the people whose hours are hardest to attribute. Facility and role conflicts are now compared **per person-week**, where the unit of work makes the comparison real.
- **HR's own copy of a credential expiry was never claimed**, so the disagreement the messy set plants between HR and the verification service could not be detected. It was the one planted problem the engine was blind to.
- **Hours-per-resident fired 44 times on one week.** A facility below the minimum for seven days is one problem with seven dates; it now reports once per site and staffing category, naming the worst day and the count. Six flags instead of forty-four.

**Two deliberate departures from the spec, both in `DECISIONS.md`**

- The person-week is keyed **without the role**. Payroll and the rota can disagree about what somebody was doing, and splitting the week by role would turn one disagreement into two half-empty weeks and a variance that is not real.
- `UNALLOCATED` is a summary tier, not a row in the daily table. The spec lists it as a tier of `daily_hours`, but it also says never to invent days — and those cannot both be true for hours with no date. They are reported as their own figure.

**Next — phase 6: views, API, and CLI**

Expiration radar, referral readiness, the facility and quarter summaries, the full API surface with SSE, and the remaining CLI exports.

**Risks**

- *Closed (R6):* carried since phase 1. The clean set raises nothing above INFO with all the domain rules live, and `make verify-clean` holds it there.
- *New:* the suite now takes 100 seconds, most of it full pipeline runs. Fine for now; if it reaches the point of not being run, the fixture scope is the thing to widen.
- *New:* every regulatory threshold is now load-bearing rather than decorative. They sit in `pack.yaml` with their sources cited and are editable in the UI, which is the defence if a judge disputes one.

---

## Phase 4 — Identity resolution ✅

**Done**

- **Weighted scoring** in the Fellegi-Sunter style, with every weight, threshold and band in the pack rather than in code. The spec's worked example scores exactly 12.0 and links automatically, as documented.
- **Five feature comparisons** — family name, given name, role, site, credential number — each returning a level, a weight, and what it compared, so a link can explain itself.
- **Resolution in the spec's order**: human decisions, then the deterministic credential anchor, then scoring. Each step is more willing to be wrong than the one before it, so each only sees what the previous could not settle.
- **Blocking** for large rosters, on family-name prefix, phonetic code, and site plus role, chosen so a true match survives at least one key.
- **One-to-one constraints** with reassignment: two records claiming one slot are either a look-alike that belongs to somebody else, or a genuine duplicate. The first is reassigned, the second stays linked and is flagged.
- **Provisional people** for everything unmatched, grouped so one unknown person appearing in two sources becomes one person rather than two.
- **Roster self-checks**: one employee number on two people, one person under two numbers, a shared phone, a shared credential.
- **Decision memory** read and applied: an accepted match overrides the score, a rejected pair is never linked.
- **A seeded 60-person benchmark** with known ground truth, and `scripts/gen_identity_benchmark.py` to regenerate it.
- **49 of 82 rules now have evaluators**, up from 36. P0 remaining: 22, down from 33.
- **563 tests passing** (65 new), ruff clean.

**Measured, not asserted**

On the benchmark — 60 people, 4 weeks, 520 records, names corrupted the way real exports corrupt them:

| | |
|---|---|
| Automatic links | 510 of 520 |
| **Precision** | **1.000** (spec target: ≥ 0.98) |
| Recall | 0.981 |
| Held back for a human | 10 — six for review, four too close to call |

Every record is either linked or flagged. Nothing is silently dropped.

**Two bugs found, one by the benchmark**

- **The uniqueness scope was not namespaced by source.** Being paid for a week and being on that week's rota are the two halves of a match, not two claims on one slot — but the scope could not tell them apart, so a correctly matched person was reported as a duplicate of themselves. It produced **205 spurious duplicate findings** on the benchmark and cost 1.2 points of precision. Fixing it took precision from 0.988 to 1.000. Ten people were never going to surface this; that is what the larger set is for.
- **An unmatched record named itself by its payroll ID** rather than by the person on it, so the ghost-employee message read "pays 'P-3012'" instead of naming them.

**A gap in the spec's rule catalog, filled**

Ingesting payroll with no roster flagged *every* row as a possible ghost employee. That is true, and useless: a roster nobody uploaded is one problem, not two hundred. The spec's own principle for mismatched coverage — "raise one flag instead of flagging every person" — applies, but there was no code for a missing source. Added `SOURCE_MISSING` (WARNING, P0), with the four expected sources declared in the pack. Unmatched records still become provisional people, so the data stays usable; they are just not each reported as unknown.

**Also**

Duplicate rota rows moved from the PDF adapter to resolution. The adapter could only compare printed text; by resolution a shortened given name and its full form are known to be one person.

**Next — phase 5: ledger, golden records, the four-way match, and the remaining rules**

The largest phase. Claims with full locators, survivorship from the authority matrix, person-week and person-day tables, and the 22 P0 rules still outstanding.

**Risks**

- *New:* precision is 1.000 on synthetic data whose corruptions I chose. The real test is the judges' file, and the review band exists precisely so borderline cases become human decisions rather than silent errors.
- *Carried (R6):* the clean set still raises nothing above INFO. Phase 5 adds the domain rules that could change that, and `make verify-clean` is the gate.

---

## Phase 3 — Normalizers and the PDF adapter ✅

**Done**

- **Seven normalizers**, each returning a value, a quality (`ok` / `repaired` / `ambiguous` / `invalid`), a note, and the rule code its outcome should raise: names, dates, phones, credential numbers, hours, codes, and shifts.
- **Nickname table**: 549 names across ~140 equivalence classes, English and Spanish, in `packs/core/nicknames.csv`.
- **The shift grammar**, shared by every pack: every written form in the spec, doubles, overnight, non-work codes, hand-written annotations, footnote parsing, and the midnight split.
- **The schedule PDF adapter**: three extraction tiers, facility matching with inference, year inference, wrapped-cell merging, per-cell bounding boxes, and segment output.
- **Two-pass normalization** wired into ingestion, plus a schedule node that runs after the tabular sources because it needs their payroll periods and home facilities.
- **36 of 81 rules now have evaluators**, up from 11. P0 remaining: 33, down from 50.
- **498 tests passing** (253 new), ruff clean.

**Verified, not assumed**

- The clean schedule PDF parses to *exactly* the hours payroll was derived from — all ten people, to the hour. That is phase 3's exit criterion and the number every later phase is measured against.
- **101 shift-grammar tests**, against the spec's ≥40.
- The clean run still raises nothing above INFO; the messy run finds every planted schedule problem; the scanned PDF blocks itself per page without crashing.
- The year comes from the payroll periods, because the printed page carries none — exactly the path the brief implies.
- Generated layout variations pass: en dashes, a missing footnote, a table spilling onto a second page, a page with no grid lines at all (rebuilt from word positions), a notes page, and a page whose title names no known facility.

**Six problems found and fixed**

- **A titleless second page inherited the first page's facility** instead of being inferred from its own staff. A continuation page and a page whose title we simply do not recognise are different things, and they are now told apart by whether anything is printed above the table.
- **The footnote parser required the shift tokens to be adjacent.** Real notes put words between them — "Day 7a-3p and evening 3p-11p are 8 hrs" — and that read as having no footnote at all. Now clause-based.
- **Splitting footnote clauses on the full stop broke "7.5 hours"** into two clauses, losing the only shift length on the page. Sentence endings are now distinguished from decimal points and from "a.m.".
- **`36h 30m` did not parse**, because the unit pattern required an `r` after the `h`.
- **Credential stripping was all-or-nothing.** `"DOE RN"` is a name and a credential; `"ANN MA"` is two names. The set is now split by whether the abbreviation is ever plausibly a surname.
- One of my own test premises was wrong: `3-1` genuinely can be read as 3am–1pm, so it is read rather than refused.

**Design decisions, all in `DECISIONS.md`**

- The footnote wins over the clock, because it is the facility stating what its shifts are worth including breaks. Where they disagree, both are kept and the difference is reported.
- A cell saying `PTO` does not say how long. The person's own usual shift that week is used, falling back to the facility's commonest, and the segment records that it was assumed.
- A bare `7-3` is matched against the shifts the page's footnote defines; with no footnote it reads as a day shift, and an implausible reading is refused rather than invented.
- Equal start and end reads as 24 hours, not zero — almost certainly a source error, and 24 gets caught by the daily cap while zero would hide it.
- Names keep two forms: a hard-folded comparison key and a display form with every accent intact.
- The adapter reports findings rather than raising flags, so it can be tested without the rule machinery.

**Next — phase 4: identity resolution**

Weighted scoring with stored explanations, the deterministic credential anchor, bands, one-to-one assignment, provisional persons, and the duplicate and collision checks.

**Risks**

- *Reduced (R1):* the PDF adapter now handles ruled tables, text layout, and bare word positions, and every page failure is isolated. The parametric generator has exercised six layout variations it had not seen. It remains the highest-variance input, but it is no longer the one I would bet on breaking.
- *New:* PTO hours are an assumption. It is recorded on every segment and shown as an assumption in the UI, but a facility whose leave day is not a normal shift length will see it in the variance.
- *Carried (R6):* the clean set still raises nothing above INFO. The domain rules that could change that arrive in phase 5.

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
