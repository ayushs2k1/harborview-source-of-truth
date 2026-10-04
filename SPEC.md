# SPEC: Harborview Source of Truth (hackathon build)

Audience: Claude Code. Owner: the person running this session.

## How to work from this spec

1. Read the whole document before writing any code.
2. Write `PLAN.md`: phases, files you will create, libraries, risks, and open questions. Then stop and wait for my approval.
3. After approval, follow **Build phases** (section 24) in order. Keep `make test` green. After every phase, update `PROGRESS.md` (done / next / risks) and commit.
4. Priorities: **P0** must work at judging. **P1** is what differentiates us. **P2** is stretch. If time runs short, cut P2, then P1. Never cut P0 robustness.

---

## 0. What we're building

A local web app plus CLI that ingests four messy files (HR roster CSV, payroll CSV, license CSV, weekly schedule PDF). It does six things:

- **Resolves identities.** Works out who is who across systems that spell names, facilities, roles, and IDs differently.
- **Keeps evidence.** Stores every source value as evidence ("claims") instead of overwriting it.
- **Builds golden records.** Picks a trusted value per attribute using a source authority matrix.
- **Runs a four-way match.** Schedule = planned, payroll = paid, HR = employed, license = permitted.
- **Flags problems.** Raises explainable flags for anything wrong, inconsistent, or needing a human.
- **Shows it all.** A live node-and-edge pipeline graph, a flag inbox, and a per-person evidence graph. Three views answer the client's problems: PBJ-ready staffing hours, an expiration radar, and referral readiness.

The engine is industry-agnostic. Healthcare is a pluggable **domain pack**, and a small trucking pack proves reuse.

Pitch line: **every number has receipts.**

## 1. The challenge (condensed)

- **Client: Pulse Foundry.** It serves established businesses whose information is scattered across systems that disagree, and it wants a source of truth it can reuse for a client in a completely different industry.
- **Business: Harborview Care Group (fictional).** Two skilled nursing facilities, **Bayside** and **Riverdale**, about 10 employees. HR, payroll, scheduling, and licensing are separate systems.
  - The facility names and the 718/347 area codes point to New York City, so New York is the default rule pack. Keep state rules swappable.
- **Their problems, in their words:**
  1. "Hospitals send us patient referrals, and by the time we get through them, the patient has often gone somewhere else."
  2. "Every quarter, reporting our staffing numbers to the state takes someone weeks, and we're never fully confident in them."
  3. "Licenses, certifications, and vendor paperwork expire, and we usually find out too late."
- **Minimum requirement:** when data is ingested, surface anything wrong, inconsistent, or needing a human.
- **Judging:**
  - They hand us the real files (same structure, different and more numerous records, messy). We ingest them live and show what the system flags.
  - We then explain how the system helps solve the three problems, grounded in what we built, and defend our decisions.
- **Submission:** the code plus a short written summary of key decisions (`DECISIONS.md`).
- **Timing:** today is early October 2026; the judging date is unknown. "As of" must be configurable everywhere.

## 2. Principles (non-negotiable)

1. **Never crash on ingest.** A bad file, page, or row becomes a flag; everything else keeps going.
2. **Never overwrite.** Store every value with its exact origin: file, row, and column, or PDF page, cell, and bounding box.
3. **Every flag has receipts.** Each one carries a plain-English message, evidence pointers, a suggested action, and an owner.
4. **Deterministic rules decide.** Optional AI helpers are advisory, validated, and off by default. The app works fully offline.
5. **Time-aware.** Compliance is judged as of the date of the work, not today. "As of" is a parameter.
6. **Unknown is never green.** Checks are three-valued: pass, fail, unknown.
7. **Config over code.** Sources, crosswalks, thresholds, rules, and the pipeline graph live in a domain pack (YAML/CSV). Never hard-code names, IDs, or dates from the samples.
8. **The graph UI is a view of the config.** It is a live view and safe editor of the pipeline config, not where logic lives.
9. **Reproducible.** Same files, same decisions, and same as-of date give identical outputs, in any file order.

## 3. Stack

- **Backend:**
  - Python 3.11+, FastAPI + Uvicorn, DuckDB (single file), Pydantic v2, PyYAML.
  - Matching: rapidfuzz (Jaro-Winkler), jellyfish (Metaphone/NYSIIS).
  - PDF: pdfplumber; pypdfium2 to render pages to PNG for the evidence viewer; reportlab to generate fixture PDFs.
  - File handling: charset-normalizer, openpyxl (accept .xlsx as a bonus), python-multipart, sse-starlette (or hand-rolled SSE).
- **Optional (P2, off by default):** pytesseract + Pillow for OCR; the `anthropic` SDK for assist features.
- **Tests:** pytest, httpx. Hypothesis is optional for normalizers.
- **Frontend:** React + TypeScript + Vite, `@xyflow/react` (React Flow), `@dagrejs/dagre` for auto-layout, react-router, Tailwind CSS. Hand-rolled components; no heavy UI kit. The Vite dev server proxies `/api` to the backend.
- **Tooling:**
  - Makefile targets: `setup`, `dev` (API on :8000, web on :5173), `demo` (load the messy sample and run), `test`, `chaos`, `lint`, `reset`.
  - Use `uv` if available, otherwise venv + pip. Pin versions.
- **Don't** use Dagster, Airflow, n8n, or Node-RED. Write a small DAG executor.

## 4. Repository layout

```
.
├── SPEC.md  PLAN.md  PROGRESS.md  DECISIONS.md  README.md
├── Makefile  pyproject.toml
├── sot/                       # industry-agnostic engine
│   ├── cli.py
│   ├── pipeline/              # spec loader, DAG executor, events, node stats
│   ├── ingest/                # file detection, CSV/XLSX reader, contracts, quarantine
│   ├── adapters/              # schedule_pdf.py (+ future adapters)
│   ├── normalize/             # names, nicknames, dates, phones, ids, hours, shifts, codes
│   ├── resolve/               # candidates, scoring, assignment, explanations
│   ├── ledger/                # claims, survivorship, golden records
│   ├── match/                 # four-way match
│   ├── rules/                 # registry, rules, flag builder
│   ├── views/                 # staffing, expirations, referral readiness
│   ├── decisions/             # aliases, mappings, dismissals, audit log
│   ├── store/                 # DuckDB schema + queries
│   ├── assist/                # optional LLM helpers (P2, off by default)
│   └── api/                   # FastAPI app, routers, SSE
├── packs/
│   ├── core/                  # nicknames.csv, shared defaults
│   ├── healthcare_ny/         # pack.yaml, pipeline.yaml, contracts/, crosswalks/, authority.yaml, rules.yaml
│   └── trucking/              # same shape
├── web/                       # Vite + React app
├── scripts/                   # generate_samples.py, make_schedule_pdf.py
├── data/samples/              # healthcare/{clean,messy,scan}/, trucking/
├── tests/                     # unit/, integration/, chaos/
├── reports/                   # CLI outputs per run
└── var/                       # DuckDB file, landed raw files, page images (gitignored)
```

## 5. Input data (from the brief)

These rows are examples only. The real files have the same structure but different, more numerous, and messier records.

**HR roster (CSV)**: one row per employee record.
```csv
employee_id,first_name,last_name,job_title,facility,phone,license_number,license_expiration,hire_date
E201,Sofia,Reyes,Registered Nurse,Harborview Bayside,718-555-0201,RN-551203,2027-05-31,2020-03-02
E202,Marcus,Bell,Certified Nursing Assistant,Harborview Riverdale,347-555-0202,CNA-771045,2026-12-31,2022-09-12
```

**Payroll (CSV)**: one row per employee per weekly pay period. There is no employee ID.
```csv
payroll_id,employee_name,job_code,facility_code,period_start,period_end,hours_paid
P-3001,"REYES, SOFIA",RN,BYS,2026-09-14,2026-09-20,36
P-3002,"BELL, MARCUS",CNA,RVD,2026-09-14,2026-09-20,40
```

**Licenses (CSV)**: one row per license or certification, from a verification service.
```csv
license_number,name_on_license,license_type,expiration_date,last_verified
RN-551203,"REYES, SOFIA",RN,2027-05-31,2026-09-01
CNA-771045,"BELL, MARCUS",CNA,2026-12-31,2026-09-01
```

**Staff schedule (PDF)**: a printed weekly schedule, as posted at the nurses' station.
- One page per facility.
- Each page has a table with one row per staff member and one column per day. Cells show the shift or OFF.
- A note at the bottom of each page gives shift lengths.

```
Staff        Role  Mon 09/14  Tue 09/15  Wed 09/16  Thu 09/17  Fri 09/18  Sat 09/19  Sun 09/20
Sofia Reyes  RN    7a-3p      7a-3p      OFF        7a-7p      OFF        7a-3p      OFF
Marc Bell    CNA   3p-11p     OFF        3p-11p     3p-11p     3p-11p     3p-11p     OFF
Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours.
```
In the real PDF, Sofia appears on the Bayside page and Marc on the Riverdale page.

**Traps already visible (handle all of them)**

*Identity and linking*
- Payroll has no employee ID, so it links only by name, job code, and facility.
- "Marc Bell" (schedule), "Marcus Bell" (HR), and "BELL, MARCUS" (payroll and licenses) are one person.
- Facility appears as "Harborview Bayside" (HR), "BYS" (payroll), and only as page-header text in the PDF. BYS = Bayside, RVD = Riverdale.
- Job title "Registered Nurse" vs code "RN"; "Certified Nursing Assistant" vs "CNA".

*File format*
- `"REYES, SOFIA"` contains the delimiter, and real files may not quote it.
- The brief shows tables aligned with spaces or tabs; real CSVs may be comma- or tab-delimited.
- Filenames may be arbitrary, so detect the source type from content.

*Schedule PDF*
- Day headers have no year ("Mon 09/14").
- Shift lengths come from the page footnote. Parse it; don't hard-code it.

*Expectations*
- The samples reconcile perfectly (36 = 36, 40 = 40). Real files won't.
- Marcus's CNA certification expires 2026-12-31, inside a 90-day window from early October 2026.

---

## 6. Ingestion: detection, contracts, quarantine

**File intake**
- Accept `.csv .tsv .txt .xlsx` (tabular) and `.pdf`. Detect the format from content, not extension.
- Store each file immutably at `var/landing/<sha256>/<original_name>` and register it in `files`.
  - A repeated sha256 raises `FILE_DUPLICATE` (INFO) and is never double counted.
- Classify each tabular file by header-signature similarity to every contract (the share of canonical columns matched).
  - The best score above 0.5 wins.
  - Ties or low scores raise `FILE_TYPE_UNKNOWN` (BLOCKER for that file). Offer a manual override in the UI and CLI (`--type payroll.csv=payroll`).
- PDFs go to the pack's schedule adapter.

**Robust tabular reading** (use our own reader, then insert into DuckDB)
- **Encoding:** try `utf-8-sig`, then `utf-8`, then charset-normalizer, then `cp1252`. Any fallback raises `ENCODING_FALLBACK` (INFO).
- **Delimiter:** sniff among `,` tab `;` `|`. Quote char `"`.
- **Header position:** the header may not be on line 1. Skip preamble lines until a row matches at least 50% of a contract's headers.
- **Non-data rows:** drop and count these as one aggregated `ROW_DROPPED_NONDATA` (INFO):
  - blank rows and repeated header rows
  - total or summary rows (first cell like "total" or "grand total", or identifier fields empty while numeric fields are filled)
  - notes rows
- **Field-count mismatch:**
  - If a row has exactly one extra field and merging two adjacent fields restores a valid "LAST, FIRST" name, repair it and raise `ROW_DELIMITER_REPAIRED` (INFO).
  - Otherwise quarantine the row with `ROW_FIELD_COUNT_MISMATCH` (WARNING).
- **Nulls:** trim whitespace. Treat `"" NA N/A #N/A NULL null None - -- — TBD ?` as null (one aggregated `NULL_TOKEN`, INFO).
- **Raw values:** keep the raw value of every cell next to the normalized value.

**Contracts** (one YAML per source, in the pack)

Each column has a canonical name, synonyms, type, required flag, normalizer, validators (regex, enum, crosswalk, range), and a description.
```yaml
source: payroll
grain: one row per employee per pay period
columns:
  - name: payroll_id
    synonyms: [pay id, check id, record id, "payroll #"]
    type: string
    required: false
  - name: employee_name
    synonyms: [name, employee, emp name, staff name, worker]
    type: person_name
    required: true
  - name: job_code
    synonyms: [job, position, position code, role, title code]
    type: code
    crosswalk: roles
    required: true
  - name: facility_code
    synonyms: [facility, site, location, dept, cost center]
    type: code
    crosswalk: facilities
    required: true
  - {name: period_start, synonyms: [start, pay period start, week start], type: date, required: true}
  - {name: period_end, synonyms: [end, pay period end, week end], type: date, required: true}
  - {name: hours_paid, synonyms: [hours, paid hours, total hours, hrs], type: hours, required: true}
```

- **Header matching order:** normalized exact synonym match (lowercase, alphanumerics only), then Jaro-Winkler ≥ 0.90, then learned `HEADER_MAP` decisions.
- **Header problems:**

| Situation | Flag | Effect |
|---|---|---|
| Two columns map to one field | `HEADER_AMBIGUOUS` (WARNING) | Keep the better score |
| Column doesn't map to anything | `HEADER_UNMAPPED_COLUMN` (INFO) | Kept as `extra.<header>` claims |
| Required column missing | `HEADER_REQUIRED_MISSING` (BLOCKER) | Affects that file only |

- **Optional columns to recognize if present:**
  - HR: `status`, `termination_date`, `email`, `middle_name`
  - Payroll: `pay_type`, `hours_worked`, `pto_hours`
  - Licenses: `status`, `state`, `issue_date`

## 7. Normalization

Every normalizer returns `(value_norm, quality ∈ {ok, repaired, ambiguous, invalid}, note)`. Aggregate "repaired" counts per column into one `VALUE_NORMALIZED` (INFO) so the inbox isn't spammed.

**Names**
- Parse into given, middle, family, and suffix.
- Handle:
  - "Last, First M." and "First M. Last" orders; ALL CAPS
  - particles (de, del, de la, da, di, van, von, le, st.)
  - hyphens and apostrophes
  - suffixes (Jr, Sr, II, III, IV)
  - trailing credentials (", RN", "LPN", "CNA")
  - repeated spaces
- Comparison key: NFKD, strip accents, lowercase, no punctuation. Display: title case of the original.

**Nicknames and variants**
- `packs/core/nicknames.csv`, bidirectional, about 200 English and Spanish pairs.
- Include spelling variants: Sofia/Sophia, Katherine/Catherine/Kate/Katie, Steven/Stephen, Marc/Mark/Marcus, William/Bill/Will, Robert/Bob/Rob, Elizabeth/Liz/Beth, José/Pepe, Francisco/Paco.
- Decisions can add aliases.

**Dates**

| Input | Handling |
|---|---|
| ISO, M/D/YYYY, M/D/YY, D-Mon-YYYY, Month D, YYYY | Parsed normally |
| Excel serials (30000–60000) | Converted; `EXCEL_SERIAL_DATE` (INFO) |
| Ambiguous day/month | Use the column's unambiguous majority; otherwise the pack default (MDY) with `DATE_AMBIGUOUS_ASSUMED` (INFO) |
| Impossible (2026-02-30) | Null; `DATE_IMPOSSIBLE` (WARNING) |
| Unparseable | Null; `DATE_UNPARSEABLE` (WARNING) |
| Two-digit years | Pivot at 70 |

**Phones**
- Keep digits only. Strip a leading 1 from 11-digit numbers.
- 10 digits is valid when the area code starts with 2–9.
- Keep extensions separately. Display as (718) 555-0201.
- 555 numbers are valid test numbers; don't flag them. Anything else invalid raises `PHONE_INVALID` (WARNING).

**License and credential numbers**
- Uppercase; strip spaces, dashes, and dots; split into an alpha prefix and digits. Infer a missing prefix from the license type.
- Match key is (type, digits). Inside the digit part, treat O as 0 and I/L as 1, and raise `LICENSE_NUMBER_CHAR_CONFUSION` (INFO) when you do.
- A prefix that contradicts the type raises `LICENSE_PREFIX_TYPE_MISMATCH` (CRITICAL).

**Hours**
- Accept `36`, `36.5`, `36,5`, `36:30` (= 36.5), `36h 30m`, `40 hrs`. Unparseable values raise `HOURS_UNPARSEABLE` (WARNING).
- Negative raises `HOURS_NEGATIVE` (WARNING; it may be a reversal).
- Over 80 per week raises `HOURS_EXCESSIVE_WEEK` (WARNING); over 168 raises the same code at CRITICAL (impossible).

**Codes** (via the pack's crosswalk CSVs)
- Facilities: "Harborview Bayside", "Bayside", "BYS", "HCG Bayside", "Harborview Care Group - Bayside" → `BYS`. Same pattern for Riverdale → `RVD`.
- Roles:

| Raw values | Canonical |
|---|---|
| "Registered Nurse", "RN", "R.N.", "Staff RN" | `RN` |
| "Licensed Practical Nurse", "LPN", "LVN" | `LPN` |
| "Certified Nursing Assistant", "Certified Nurse Aide", "CNA", "Nurse Aide", "STNA" | `CNA` |
| "Director of Nursing", "DON" | `RN_DON` |

- Ambiguous titles ("Charge Nurse", "Nurse") resolve through the linked license type.
- Unknown codes raise `CODE_UNKNOWN_FACILITY` or `CODE_UNKNOWN_ROLE` (WARNING) with a one-click mapping (a `CODE_MAP` decision).

## 8. Schedule PDF adapter

**Extraction**
- **Text layer present:** use pdfplumber `extract_tables` (lines strategy, then text strategy).
- **Fallback:** cluster words by position. Rows come from y; columns come from the x-positions of the header words ("Staff" or "Name", "Role", and the seven day headers).
- **Both fail:** raise `PDF_TABLE_NOT_FOUND` (BLOCKER for that page).
- **No text layer:**
  - If pytesseract is available, OCR the page image and run the same clustering (INFO; low confidence).
  - Otherwise raise `PDF_NO_TEXT_LAYER` (BLOCKER for that page).
- **Optional vision-LLM fallback (P2):** only when enabled in settings with an API key present. Its output must pass the same validation and is marked low confidence for review.

**Facility**
- Match the page text, title area first, against the facility crosswalk aliases.
- If nothing matches, infer the facility from the majority home facility of staff on the page and raise `PDF_FACILITY_UNKNOWN` (WARNING).
- If neither works, the page is a BLOCKER.

**Day headers**
- Parse "Mon 09/14", "Monday 9/14", "9/14 Mon", and "09/14/2026".
- Infer the year in this order:
  1. an explicit year on the page
  2. payroll periods covering those dates
  3. the year that puts the date nearest the as-of date
- Handle a Dec→Jan rollover within one week.
- If the weekday doesn't match the date, raise `WEEKDAY_DATE_MISMATCH` (WARNING) and trust the date.

**Footnote**
- Parse sentences like "7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."
- Generic pattern: a list of shift tokens, then "is" or "are", then a number, then hour(s).
- If the footnote is missing, raise `PDF_FOOTNOTE_MISSING` (WARNING) and use clock math.

**Page structure**
- A page with the table header but no facility continues the previous page's facility (INFO).
- Wrapped cells: merge continuation lines into the row above when the Staff cell is empty.
- For every cell, store page, row index, column header, text, bounding box (for the evidence viewer), extraction method, and confidence.

**Shift grammar** (one parser shared by all packs)
- Normalize dashes (– — − ‐) and spaces.
- Accepted forms:
  - `7a-3p`, `7A-3P`, `7am-3pm`, `7:00a-3:00p`, `7:00 AM - 3:00 PM`
  - `0700-1500`, `07:00-15:00`
  - overnight: `7p-7a`, `11p-7a`
  - doubles: `7a-3p/3p-11p`, `7a-3p, 3p-11p`, `7a-11p`
- `7-3` is ambiguous: map it using the page's footnote shift set and raise `SHIFT_AMBIGUOUS_ASSUMED` (INFO).
- Ignore trailing markers like `*`, `(C)`, or `CN`, but keep them as notes.

**Non-work codes**

| Cell values | Category | Handling |
|---|---|---|
| `OFF`, `Off`, `O`, `X`, blank, `-`, `—` | OFF | No hours |
| `PTO`, `VAC`, `VACATION`, `SICK`, `SL`, `HOL`, `LOA`, `FMLA`, `BRV` | PTO | Paid but not worked; `PTO_ON_SCHEDULE` (INFO) |
| `ORIENT`, `ORIENTATION`, `TRN`, `TRAINING`, `INSERVICE` | TRAINING | Counts as worked for reconciliation; PBJ inclusion is a pack setting (default false) |
| `OC`, `ON CALL` | ONCALL | Not worked |
| Anything else | — | `SHIFT_UNPARSEABLE` (WARNING, cell-level) |

**Hours per segment**
- When the token is defined in the footnote, use the footnote hours; they are authoritative for that page.
- Otherwise use the clock duration (overnight-aware) and raise `SHIFT_NOT_IN_FOOTNOTE` (INFO).
- If footnote and clock math disagree, use the footnote and raise `FOOTNOTE_CLOCK_MISMATCH` (INFO).
- A segment running past the last date of the period raises `SHIFT_SPANS_PERIOD` (INFO).

**Output:** `shift_segments` with person reference, facility, role, start date, start and end timestamps, hours, category, and cell refs.
- A person who appears on two facility pages raises `PERSON_ON_MULTIPLE_PAGES` (INFO); this is a legitimate float.

## 9. Identity resolution

**Entities and IDs**
- Entities are Person, Facility, and Credential. HR rows seed persons.
- Stable `person_id` is `P-<employee_id>` when an employee ID exists.
- Otherwise it is a provisional ID from a hash of the first record's normalized name + role + facility, with `status = provisional`.

**Order of operations**
1. Apply human decisions (accepted aliases, rejected pairs).
2. Deterministic anchor: link HR `license_number` to the licenses file's `license_number` by normalized key.
3. Weighted scoring for payroll rows, schedule rows, and any license rows not linked by number.

**Candidates:** all persons if there are 2,000 or fewer. Otherwise block on last-name prefix, phonetic code, or same facility + role.

**Score:** the sum of hand-set log2 match weights (Fellegi-Sunter style), kept in pack config.

| Feature | Comparison levels → weight |
|---|---|
| Last name | exact +6.0 · Jaro-Winkler ≥ 0.94 +4.0 · phonetic (Metaphone/NYSIIS) +3.0 · else −6.0 |
| First name | exact +4.5 · nickname/variant +3.5 · Jaro-Winkler ≥ 0.90 +2.5 · initial only +1.0 · else −4.5 |
| Role (canonical) | same +1.5 · compatible +0.5 · different −2.0 |
| Facility | same +1.0 · different −1.0 (floats exist) |
| Credential number (when both have one) | exact +12.0 · different −6.0 |

**Bands**

| Score | Outcome |
|---|---|
| ≥ 8.0 | Auto-link |
| 3.0–8.0 | Review: `MATCH_REVIEW` (WARNING) |
| < 3.0 | No link |
| Top two candidates within 2.0 of each other | `MATCH_AMBIGUOUS` (WARNING); don't auto-link |

**One-to-one constraints** (resolve conflicts greedily by score)
- Per pay period, a person gets at most one payroll row per role + facility. Extras raise `DUPLICATE_PAY_PERIOD`.
- Per schedule page, a person appears at most once. Extras raise `DUPLICATE_SCHEDULE_ROW`.

**Unmatched records** become provisional persons so they stay visible, and raise `UNMATCHED_PAYROLL`, `UNMATCHED_SCHEDULE`, or `UNMATCHED_LICENSE`.

**Duplicate and collision checks**

| Situation | Flag |
|---|---|
| HR rows with the same name + phone or license under different IDs | `DUPLICATE_PERSON_HR` |
| Same employee ID with different names | `EMPLOYEE_ID_COLLISION` |
| Same credential number on two persons | `LICENSE_NUMBER_SHARED` |
| Two persons sharing a phone number | `SHARED_PHONE` (WARNING, P1) |

**Explanations:** every link stores its features (comparison level, values compared, weight), the total, the band, and `decided_by` (auto | human). The UI renders this as a waterfall.

**Worked example:** schedule "Marc Bell / CNA / Riverdale" vs HR "Marcus Bell / CNA / Riverdale" = 6.0 + 3.5 + 1.5 + 1.0 = 12.0 → auto-link.

## 10. Claims ledger and golden records

**Claims.** Every normalized value becomes a claim:
`(claim_id, run_id, entity_type, entity_id, attribute, value_raw, value_norm, source_type, file_id, locator, observed_on, quality)`
- `locator` is `{row, column}` for tabular files or `{page, row, column, bbox}` for PDFs.
- `observed_on` is the date the source vouches for the value, e.g. `last_verified` or the pay period end.

**Golden records.** Survivorship is decided per attribute from `authority.yaml`:
1. ordered sources
2. tie-break by `observed_on` recency
3. then completeness

Store the chosen `claim_id` and the rule used.

**Default authority (healthcare pack):**

| Attribute | Authority order |
|---|---|
| Legal name, employee_id, hire_date, phone, home facility, HR job title | hr › licenses › payroll › schedule |
| Credential number, type, expiration, last_verified, name on credential | licenses › hr |
| Hours paid, pay period, paid job code, paid facility | payroll |
| Worked date, shift times, worked facility, worked role | schedule |

**Conflicts.** When an attribute has distinct normalized values, keep all of them and raise the attribute-specific flag (`HR_LICENSE_EXPIRY_STALE`, `NAME_MISMATCH_LICENSE`, `FACILITY_CONFLICT`, `ROLE_CONFLICT`, …). The authority only decides what the golden record displays.

**Rebuild.** Recompute derived tables from the full ledger on every run, so file order never matters.

## 11. Four-way match

The four legs:
- **Planned:** the schedule
- **Paid:** payroll
- **Employed:** HR
- **Permitted:** credentials

**Person-week** (one per pay period)

| Measure | Definition |
|---|---|
| `scheduled_work_hours` | WORK + TRAINING segments, attributed by shift start date (pack setting `payroll_attribution: shift_start`) |
| `scheduled_pto_hours` | PTO segments |
| `paid_hours` | From payroll |
| `employed` | In HR, `hire_date ≤ period_end`, and not terminated before `period_start` |
| `permitted` | Every worked date is covered by a valid credential of sufficient type, when the role requires one |

- **Primary status** (exactly one): `MATCHED`, `HOURS_VARIANCE` (direction `PAID_MORE` or `PAID_LESS`, plus delta), `PAID_NOT_SCHEDULED`, `SCHEDULED_NOT_PAID`, `NOT_EMPLOYED`, `NOT_PERMITTED`, or `UNKNOWN`.
- **Tolerance:** ±0.25 h (pack setting).
- **PTO:** if `paid − scheduled_work ≈ scheduled_pto`, mark the week "explained by PTO" (INFO instead of WARNING).
- **Coverage first:** compare only periods covered by both sources. If schedule and payroll cover different weeks, raise one `COVERAGE_GAP_BETWEEN_SOURCES` (INFO) instead of flagging every person.

**Person-day** (one per worked date) records:
- facility, role, and segments
- whether a credential is valid on that date
- whether the person is employed on that date
- overlaps with other segments (`OVERLAPPING_SHIFTS`, CRITICAL)

These tables drive the staffing view and many of the rules.

---

## 12. Flags

```
flag_id          stable hash(rule_code, primary entity keys, key evidence values)
rule_code        e.g. UNMATCHED_PAYROLL
severity         BLOCKER | CRITICAL | WARNING | INFO
category         FILE | FORMAT | IDENTITY | CROSS_SOURCE | TIME | PDF | DOMAIN
title            short
message          plain English with the actual names, dates and numbers
entities         [{type, id, display}]
evidence         [{file, source_type, row | page, column, raw_value, bbox?}]
suggested_action
owner_role       HR | PAYROLL | DON | ADMINISTRATOR | DATA_STEWARD
due_date         optional
status           OPEN | RESOLVED | DISMISSED(reason); first_seen_run, last_seen_run
```

**Severity**

| Level | Meaning |
|---|---|
| BLOCKER | A file or page couldn't be processed. Only that file or page is affected. |
| CRITICAL | Compliance, safety, or money is at risk. |
| WARNING | Needs human judgment. |
| INFO | Auto-fixed or informational; aggregated per column or file. |

**Row numbers** follow spreadsheet convention: the header is row 1 and the first data row is row 2. PDF pages are 1-based.

**Message style** (format examples only; never hard-code):
- "Marcus Bell's CNA certification (CNA-771045) expires Dec 31, 2026, 88 days after the as-of date. He has 5 shifts on the Sep 14–20 schedule at Riverdale. In NY the employing facility files CNA recertification; payroll shows 40 paid CNA hours in the week of Sep 14 (7 needed in the prior 24 months)."
- "Payroll row P-3007 pays 'GARCIA, ANA' 32 hours at RVD for Sep 14–20, but no matching person exists in the HR roster."
- "Riverdale has no RN on duty for 8 consecutive hours on Sun Sep 20."

## 13. Rule catalog

Implement a registry. Each rule has a code, default severity, category, priority, a function, and parameters from the pack. Generate `docs/RULES.md` from the registry.

**File and structure**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `FILE_TYPE_UNKNOWN` | BLOCKER | P0 | Can't tell which source a file is; offer an override |
| `FILE_DUPLICATE` | INFO | P0 | Same file seen before; not double counted |
| `HEADER_REQUIRED_MISSING` | BLOCKER | P0 | Required column missing (that file only) |
| `HEADER_UNMAPPED_COLUMN` | INFO | P0 | Extra column kept as extra claims |
| `HEADER_AMBIGUOUS` | WARNING | P1 | Two columns map to one field |
| `ROW_FIELD_COUNT_MISMATCH` | WARNING | P0 | Row quarantined |
| `ROW_DELIMITER_REPAIRED` | INFO | P0 | Unquoted "LAST, FIRST" repaired |
| `ROW_DROPPED_NONDATA` | INFO | P0 | Blank, header-repeat, total, or notes rows (count) |
| `ENCODING_FALLBACK` | INFO | P1 | File decoded with a fallback encoding |
| `VOLUME_DROP` | WARNING | P2 | Row count fell more than 30% vs the previous run of the same source |

**Format**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `VALUE_NORMALIZED` | INFO | P0 | Values reformatted (aggregated) |
| `NULL_TOKEN` | INFO | P1 | Null tokens found (aggregated) |
| `DATE_UNPARSEABLE` | WARNING | P0 | Date couldn't be read |
| `DATE_IMPOSSIBLE` | WARNING | P0 | Date doesn't exist |
| `DATE_AMBIGUOUS_ASSUMED` | INFO | P1 | Day/month order assumed |
| `EXCEL_SERIAL_DATE` | INFO | P1 | Excel serial converted |
| `PHONE_INVALID` | WARNING | P0 | Phone number invalid |
| `LICENSE_PREFIX_TYPE_MISMATCH` | CRITICAL | P0 | License prefix contradicts its type |
| `LICENSE_NUMBER_CHAR_CONFUSION` | INFO | P1 | O/0 or I/L/1 substitution applied |
| `HOURS_UNPARSEABLE` | WARNING | P0 | Hours couldn't be read |
| `HOURS_NEGATIVE` | WARNING | P0 | Negative hours; possibly a reversal |
| `HOURS_EXCESSIVE_WEEK` | WARNING >80, CRITICAL >168 | P0 | Implausible weekly hours |
| `CODE_UNKNOWN_FACILITY` | WARNING | P0 | Facility code not in the crosswalk |
| `CODE_UNKNOWN_ROLE` | WARNING | P0 | Role code not in the crosswalk |

**Identity**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `MATCH_REVIEW` | WARNING | P0 | Score in the review band |
| `MATCH_AMBIGUOUS` | WARNING | P0 | Top two candidates too close |
| `UNMATCHED_PAYROLL` | CRITICAL | P0 | Paid but not in HR: a ghost-employee red flag, or unrecorded agency staff |
| `UNMATCHED_SCHEDULE` | CRITICAL if the role needs a license, else WARNING | P0 | Scheduled but not in HR |
| `UNMATCHED_LICENSE` | WARNING | P0 | License row matches no person |
| `LICENSE_NOT_IN_SERVICE` | CRITICAL if working a licensed role in the data period, else WARNING | P0 | HR lists a license number the verification service doesn't have |
| `DUPLICATE_PERSON_HR` | WARNING | P0 | Same person under two HR IDs |
| `EMPLOYEE_ID_COLLISION` | CRITICAL | P0 | One ID, two different people |
| `LICENSE_NUMBER_SHARED` | CRITICAL | P0 | One credential number on two people |
| `NAME_MISMATCH_LICENSE` | WARNING | P0 | Linked by number but names differ (maiden name?) |
| `DUPLICATE_SCHEDULE_ROW` | WARNING | P1 | Person listed twice on one page |
| `SHARED_PHONE` | WARNING | P1 | Two people share a phone number |

**Cross-source (four-way match)**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `COVERAGE_GAP_BETWEEN_SOURCES` | INFO | P0 | Sources cover different periods |
| `PAID_NOT_SCHEDULED` | WARNING | P0 | Paid hours with no scheduled shifts |
| `SCHEDULED_NOT_PAID` | WARNING | P0 | Scheduled shifts with no pay |
| `HOURS_VARIANCE` | WARNING (INFO when explained by PTO) | P0 | Paid and scheduled hours differ beyond tolerance |
| `FACILITY_CONFLICT` | WARNING | P0 | Systems disagree on facility; PBJ hours follow where the work happened |
| `ROLE_CONFLICT` | WARNING | P0 | Systems disagree on role |
| `ROLE_EXCEEDS_LICENSE` | CRITICAL | P0 | Any role claim (HR title, payroll job code, schedule role) is above what the credential allows: scope of practice, and the wrong PBJ code |
| `LICENSED_ROLE_NO_CREDENTIAL` | CRITICAL | P0 | Licensed role with no credential |
| `HR_LICENSE_EXPIRY_STALE` | WARNING | P0 | HR's copy of the expiry disagrees with the license service |
| `DUPLICATE_PAY_PERIOD` | CRITICAL | P0 | Possible double pay |
| `PAYROLL_PERIOD_INVALID` | WARNING | P0 | Period isn't 7 days, doesn't start on the pack's week start, or ends before it starts |
| `OVERLAPPING_SHIFTS` | CRITICAL | P0 | Same person in two places at once |

**Time**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `WORKED_AFTER_EXPIRY` | CRITICAL | P0 | Worked after the credential expired, judged as of the shift date |
| `SCHEDULED_AFTER_EXPIRY` | CRITICAL | P0 | Forecast: scheduled after expiry |
| `CREDENTIAL_EXPIRING` | WARNING at 90/60 days, CRITICAL at 30/14 days | P0 | Expiry approaching |
| `CREDENTIAL_EXPIRED` | CRITICAL if active in a licensed role, else WARNING | P0 | Credential already expired |
| `VERIFICATION_STALE` | WARNING | P0 | `last_verified` older than `verification_max_age_days` |
| `VERIFIED_DATE_IN_FUTURE` | WARNING | P1 | Verification date is in the future |
| `ACTIVITY_BEFORE_HIRE` | CRITICAL | P0 | Paid or scheduled before the hire date |
| `HIRE_DATE_IN_FUTURE` | WARNING | P1 | Hire date is in the future |
| `WEEKDAY_DATE_MISMATCH` | WARNING | P0 | Schedule weekday doesn't match its date |
| `DAILY_HOURS_OVER_CAP` | CRITICAL | P0 | Over 22.5 h in a day; PBJ would reject it |
| `LONG_DAY` | WARNING | P1 | Day longer than the fatigue limit |
| `SHORT_REST` | INFO | P1 | Too little rest between shifts |
| `CONSECUTIVE_DAYS` | INFO | P1 | Too many days in a row |

**Schedule PDF**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `PDF_NO_TEXT_LAYER` | BLOCKER for the page, or INFO if OCR is used | P0 | Scanned page |
| `PDF_TABLE_NOT_FOUND` | BLOCKER for the page | P0 | No table could be extracted |
| `PDF_FACILITY_UNKNOWN` | WARNING, or BLOCKER if it can't be inferred | P0 | Page facility not recognized |
| `PDF_FOOTNOTE_MISSING` | WARNING | P0 | No shift-length note; clock math used |
| `SHIFT_UNPARSEABLE` | WARNING | P0 | Cell couldn't be read |
| `SHIFT_NOT_IN_FOOTNOTE` | INFO | P0 | Hours computed from clock times |
| `PTO_ON_SCHEDULE` | INFO | P0 | Paid time off on the schedule |
| `FOOTNOTE_CLOCK_MISMATCH` | INFO | P1 | Footnote hours differ from clock math |
| `SHIFT_AMBIGUOUS_ASSUMED` | INFO | P1 | Ambiguous shift mapped using the footnote |
| `SHIFT_SPANS_PERIOD` | INFO | P1 | Shift runs past the period end |
| `PERSON_ON_MULTIPLE_PAGES` | INFO | P1 | Legitimate float across facilities |

**Domain (healthcare_ny)**

| Code | Severity | Pri | What it means |
|---|---|---|---|
| `RN_8H_COVERAGE_GAP` | CRITICAL | P0 | A facility-day inside schedule coverage without RN coverage for 8 consecutive hours |
| `PBJ_UNALLOCATED_HOURS` | WARNING | P0 | Paid hours with no schedule day; never invent days |
| `PBJ_TRACEABILITY_VARIANCE` | WARNING | P0 | Per facility-period, schedule-derived worked hours and paid hours (minus PTO) differ by more than 4% |
| `ZERO_RN_DAYS_QUARTER` | WARNING at 4, CRITICAL at 7 | P1 | Count of zero-RN days per facility per quarter |
| `CNA_EXPIRY_NOT_MONTH_END` | INFO | P1 | Likely data-entry error; NY CNA renewals fall on month-ends |
| `CNA_RECERT_EVIDENCE_INSUFFICIENT` | WARNING | P1 | Fewer than 7 paid aide hours inside 24 months in the available payroll |
| `CNA_HOURS_EXCLUDED_UNCERTIFIED` | WARNING | P1 | CNA hours on dates without valid certification are excluded from the CNA bucket |
| `HPRD_BELOW_MINIMUM` | CRITICAL | P1 | Below hours-per-resident-day minimums (only when census is provided) |

## 14. Healthcare (NY) domain pack

**Domain facts.** Keep every number in pack config with its source URL in a comment. All thresholds are configurable.

**NY minimum staffing (Public Health Law §2895-b)**
- "Staffing hours" are the hours reported to CMS through PBJ. Compliance is determined quarterly against census.
- Minimums: 3.5 nursing hours per resident per day (HPRD) in total, at least 2.2 from CNAs and at least 1.1 from licensed nurses (RN + LPN).
- Penalties run up to $2,000 per day.
- Since 2023, only certified aide hours count toward the aide requirement.
- Sources:
  - https://newyork.public.law/laws/n.y._public_health_law_section_2895-b
  - https://healthweb-back.health.ny.gov/facilities/nursing/minimum_staffing/
  - https://leadingageny.org/providers/nursing-homes/survey-clinical-and-quality1/new-pbj-data-tell-old-story/

**CMS Payroll-Based Journal (PBJ)**
- Requires daily hours per employee by job title.
- Hours are reported by calendar day with midnight as the cutoff, so overnight shifts are split.
- Meal time is excluded, paid or unpaid.
- The current file spec rejects more than 22.5 hours per employee ID per day.
- Due 45 days after quarter end, on federal fiscal quarters: Q1 Oct–Dec, Q2 Jan–Mar, Q3 Apr–Jun, Q4 Jul–Sep.
- Audits compare submissions to payroll, timekeeping, and invoices. CMS has described a gap above 4% between submitted and verified hours as significant.
- Care Compare has long given a one-star staffing rating for 7 or more days in a quarter with no RN hours.
- Sources:
  - https://viventium.com/skilled-nursing-facilities-and-payroll-based-journals
  - https://www.simpleltc.com/wp-content/uploads/2025/10/Webinar-Slides-PBJ-Webinar-Q4-2025-1.pdf
  - https://www.ahcancal.org/News-and-Communications/Blog/Pages/Upcoming-PBJ-Deadline-Reminder-.aspx
  - https://skillednursingnews.com/2018/11/cms-peels-back-curtain-providers-receive-pbj-audits/
  - https://theconsumervoice.org/news/detail/all/cms-memo-on-pbj

**Federal RN rule (restored December 2025)**
- An RN on duty at least 8 consecutive hours a day, 7 days a week.
- A full-time RN director of nursing.
- Source: https://www.aha.org/news/headline/2025-12-02-cms-repeals-minimum-staffing-requirements-skilled-nursing-long-term-care-facilities

**NY CNA recertification**
- Every 2 years, due by the last day of the month of the original certification.
- Requires at least 7 paid hours as a nurse aide in the prior 24 months.
- Filed by the employing nursing home (or the employing staffing agency).
- Source: https://www.leadingageny.org/providers/nursing-homes/doh-releases-cna-re-certification-reminder-dal

**PBJ job title codes** (verify against CMS's current list)

| Role | Code |
|---|---|
| RN director of nursing | 5 |
| RN with administrative duties | 6 |
| RN | 7 |
| LPN with administrative duties | 8 |
| LPN | 9 |
| CNA | 10 |
| Aide in training | 11 |
| Medication aide | 12 |

**Defaults (`pack.yaml`)**
```yaml
as_of: today
week_start: monday
date_order_default: MDY
hours_tolerance: 0.25
payroll_attribution: shift_start
pbj:
  split_at_midnight: true
  meal_deduction: {minutes: 30, min_shift_hours: 6}   # assumption, shown in the UI and editable
  include_training: false
  daily_cap_hours: 22.5
  traceability_variance_pct: 4.0
zero_rn_days: {warn: 4, critical: 7}                    # per facility per quarter
rn_min_consecutive_hours: 8
rn_coverage_mode: union                                 # union of RN segments, or single_person
tours: {day: "07:00-15:00", evening: "15:00-23:00", night: "23:00-07:00"}
expiry_windows_days: [90, 60, 30, 14]
verification_max_age_days: 60
fatigue: {long_day_hours: 16, min_rest_hours: 8, max_consecutive_days: 7}
hprd_minimums: {total: 3.5, licensed: 1.1, cna: 2.2}
required_credential:
  RN: [RN]
  RN_DON: [RN]
  RN_ADMIN: [RN]
  LPN: [LPN, RN]
  CNA: [CNA, LPN, RN]   # LPN/RN working as aide → INFO "working below license level"
  MED_AIDE: [MED_AIDE]
```

**Crosswalks**
- `crosswalks/facilities.csv`: code, name, aliases (pipe-separated). Seed BYS = Harborview Bayside and RVD = Harborview Riverdale with the aliases above.
- `crosswalks/roles.csv`: canonical code, PBJ code, licensed (bool), aliases.

**Assumption to surface in the UI:** with meal deduction on, Sofia's 36 paid hours become about 34 PBJ hours (4 shifts × 30 min). Show this as an explicit, editable assumption next to the staffing numbers.

## 15. Views (the three problems)

### Staffing: PBJ-ready daily hours

**Table `daily_hours`:** facility, work_date, person_id, display_name, role, pbj_job_code, scheduled_hours (after the midnight split), meal_deduction, pbj_hours, tier, evidence.

**Tiers**

| Tier | When |
|---|---|
| `VERIFIED` | The person-week is MATCHED |
| `CONFLICT` | The person-week has a variance; hours are shown and flagged |
| `SCHEDULE_ONLY` | No payroll; not reportable |
| `UNALLOCATED` | Paid hours with no schedule day. Never invent days. |

**Summary per facility, per period and per quarter**
- Hours by RN, LPN, and CNA.
- % verified and unallocated hours.
- Zero-RN days vs thresholds, and daily-cap violations.
- Traceability variance vs 4%.
- PBJ quarter label and due date, e.g. "FFY2026 Q4 (Jul–Sep), due Nov 14, 2026".

**Optional census.** Accept `census.csv` (facility, date, residents) or a per-facility number typed in the UI. When present, show daily HPRD indicators vs 3.5 / 1.1 / 2.2, and exclude uncertified aide hours from the CNA bucket.

**Export:** CSV.

### Expiration radar

- Covers every credential, plus optional `vendor_documents.csv` (vendor, doc_type, doc_number, expires_on, verified_on). Vendor documents use the same credential model, with the organization as holder.
- **Columns:**
  - holder, type, number
  - expires_on, days_left (vs as-of), band
  - last_verified and its age
  - next scheduled shift after expiry, and shifts worked after expiry
  - NY CNA recertification readiness: paid aide hours found inside 24 months vs the 7 required
- Sorted by urgency, with filters for band, facility, and type.

### Referral readiness

**Inputs:** facility, a date inside schedule coverage, optional census, and a "+1 resident" toggle.

**Outputs**
- RN coverage: whether there are 8 consecutive hours, and which RNs, when.
- Licensed and aide hours.
- Whether a licensed nurse is on each tour (day / evening / night), as an operational metric.
- On-duty staff with their credential status.
- Open critical flags touching that facility-day.
- HPRD before and after +1 (with census).
- A verdict, `YES` / `NO` / `UNKNOWN`, with reasons.

Label this as a fast admissions indicator; NY compliance itself is a quarterly average.

## 16. Decisions (human input becomes memory)

| Type | Meaning |
|---|---|
| `ACCEPT_MATCH` | Record fingerprint → person |
| `REJECT_MATCH` | Record fingerprint ↛ person |
| `CODE_MAP` | Code type + raw value → canonical code |
| `HEADER_MAP` | Source + raw header → canonical column |
| `DISMISS_FLAG` | flag_id + reason |
| `NOTE` | Free-text note |

- **Record fingerprint:** source_type + normalized name + role + facility. It deliberately excludes row numbers, so it survives re-exports.
- **Storage:** DuckDB `decisions` table (actor, reason, created_at), with export/import to `var/decisions.yaml`.
- **Lifecycle:** applied at the start of every run. `make reset` clears them. The UI shows the audit log.

---

## 17. Pipeline spec and executor

**Spec file:** `packs/<pack>/pipeline.yaml` defines nodes (id, type, label, config) and edges.

**Node types and typed ports**

| Node type | Takes | Produces |
|---|---|---|
| `source` | — | RawTable |
| `standardize` | RawTable | StdTable |
| `resolve` | StdTable* | Links |
| `ledger` | StdTable* + Links | Claims, Golden |
| `match` | Golden + Std | MatchTables |
| `rules` | everything | Flags |
| `view` | … | View |

Reject wiring that doesn't type-check, and reject cycles.

**Executor**
- Runs nodes in topological order, each wrapped in try/except.
- A failure becomes a BLOCKER flag for that node; downstream nodes run with what's available and are marked "degraded".

**Events**
- `node_started`, `node_progress`, `node_finished {rows_in, rows_out, quarantined, flags_by_severity, duration_ms}`, `run_finished`.
- Persist them in `run_events` and stream them over SSE.

**Safe edits from the UI**
- Parameters only: thresholds, tolerances, windows, rule toggles, pack selection.
- Validated against a JSON schema and saved to `var/overrides.yaml`; pack defaults stay untouched.
- Structural edits are out of scope unless time remains.

## 18. Storage (DuckDB)

Write `sot/store/schema.sql`. Derived tables are keyed by `run_id`; the UI shows the latest run.

| Group | Tables |
|---|---|
| Runs and files | `runs`, `files`, `raw_rows`, `pdf_cells`, `quarantine` |
| Standardized sources | `std_hr`, `std_payroll`, `std_licenses`, `shift_segments` |
| Entities and evidence | `persons`, `links`, `claims`, `golden_attributes`, `credentials`, `pay_lines` |
| Match and views | `match_person_week`, `match_person_day`, `daily_hours` |
| Flags and decisions | `flags`, `flag_evidence`, `decisions` |
| Run telemetry | `node_stats`, `run_events` |

## 19. API (FastAPI, JSON) and CLI

```
POST /api/ingest                    multipart files[], as_of?, pack?, type_overrides? → {run_id}
GET  /api/runs | /api/runs/{id}     run list | summary + node stats
GET  /api/runs/{id}/events          SSE stream
POST /api/runs/{id}/rerun           same files, current decisions and params
POST /api/runs/{id}/replay          replay stored events (demo fallback, no recompute)
GET  /api/pipeline                  pack pipeline spec + latest node stats
PUT  /api/pipeline/params           safe parameter edits (validated)
GET  /api/flags                     filters: run_id, severity, category, status, entity_id, rule_code
GET  /api/flags/{id}                detail + evidence
POST /api/decisions | GET /api/decisions
GET  /api/persons | /api/persons/{id} | /api/persons/{id}/graph
GET  /api/evidence/file/{file_id}/row/{n}
GET  /api/evidence/pdf/{file_id}/page/{p}.png
GET  /api/views/staffing?facility&from&to
GET  /api/views/expirations
GET  /api/views/referral?facility&date&census&plus_one
GET  /api/exports/{name}.csv
GET  /api/chaos/coverage
GET  /api/packs | /api/health
```

**CLI:** `python -m sot ingest DIR --as-of YYYY-MM-DD --pack healthcare_ny [--type FILE=SOURCE]`
- Writes `reports/<run_id>/{flags.csv, flags.json, pbj_daily_hours.csv, expirations.csv, referral_readiness.csv, summary.md}`.
- Exits 0 even when the data is bad. It exits non-zero only on a real crash, which should never happen.

## 20. Frontend

**Global**
- Left nav: Ingest, Pipeline, Flags, People, Staffing, Expirations, Referrals, Chaos, Settings.
- Header strip: data period, as-of date, pack, PBJ quarter and due date.
- Clean, neutral design that reads well on a projector at 1280px.
- Severity colors: CRITICAL red, WARNING amber, INFO gray, BLOCKER dark purple. Always pair color with an icon or text.

**Ingest**
- Drag-and-drop zone. Each file shows its detected source type and confidence, with an override dropdown.
- As-of date picker (default today) and pack selector.
- "Ingest" starts a run and opens Pipeline.

**Pipeline**
- React Flow canvas built from `/api/pipeline`, laid out left→right with dagre.
- Custom node cards show label, status color, rows in/out, quarantined count, and flag counts by severity.
- Edges are labeled with row counts and animate while the run streams in over SSE. Include MiniMap and Controls.
- Clicking a node opens a drawer with:
  - a summary and sample output rows (first 20)
  - that node's flags
  - a parameter editor for safe edits
  - a "Re-run" button
- A "Replay last run" button serves as the demo fallback.

**Flags**
- Severity tabs with counts, plus filters.
- Cards show the title, message, and entity chips that link to People.
- Evidence opens a viewer: the CSV row with the cell highlighted, or the PDF page image with the bounding box highlighted.
- Actions: accept or reject a match, map a code or header, dismiss with a reason.
- INFO flags collapse into aggregates ("23 values auto-normalized").

**People**
- Table of persons: golden name, role, home facility, credential status, flag count.
- Person page:
  - **Evidence graph (React Flow):** the golden node in the center, source records around it, edges labeled with match scores, conflicts in red. Clicking an edge shows the score waterfall.
  - **Attribute table:** golden value, winning source, other claims.
  - Credentials, and a mini shift grid.

**Staffing**
- Facility tabs and a day × role hours grid, colored by tier, with a legend.
- KPIs: % verified, unallocated hours, variance vs 4%, zero-RN days, cap violations.
- Assumptions panel: meal deduction, midnight split, attribution.
- CSV export.

**Expirations**
- Urgency-sorted list or timeline with band chips.
- Badges: scheduled past expiry, worked after expiry, stale verification.
- CNA recertification evidence.

**Referrals**
- Form: facility, date, census, +1.
- Verdict card with reasons and supporting metrics.

**Chaos**
- Coverage matrix: mutation → expected codes → pass/fail.

**Settings**
- As-of date, tolerances, thresholds, expiry windows, meal policy, rule toggles.
- Pack switcher and "Reset demo".

## 21. Fixtures, generators, and the chaos deck

### Generator

`scripts/generate_samples.py --seed 42` is deterministic and produces:

**`data/samples/healthcare/clean/`**
- The brief's rows plus about 8 invented employees: 10 total across both facilities, one or two weeks, fully consistent.
- It must satisfy every domain rule, e.g. an RN on duty for 8 consecutive hours on every facility-day. The float gets one payroll row per facility, matching their hours at each.
- The schedule PDF is made with reportlab and mirrors the described layout: a title with facility name and week, the table, the footnote, one page per facility.
- Small optional `census.csv` and `vendor_documents.csv` samples.

**`data/samples/healthcare/messy/`** (used by `make demo`): the clean set with at least these problems planted:
- a ghost payroll row
- an agency nurse who appears only on the schedule
- a nickname on the schedule, and an accent mismatch
- an expired license with shifts, a license expiring within 90 days, and a stale verification
- an HR vs license-service expiry mismatch
- one hours variance explained by PTO and one unexplained
- an undefined shift (7p-7a) and an overnight 11p-7a
- an unquoted "LAST, FIRST" comma
- a facility-day with no RN
- a duplicate payroll row
- an unknown facility code

**`data/samples/healthcare/scan/`:** the schedule rasterized into an image-only PDF.

**`data/samples/trucking/`:** see section 22.

**Tricky names to include**
- José Peña (accent)
- Ana García-López (hyphenated surname)
- Kevin O'Brien (apostrophe)
- Robert Hayes Jr. (suffix)
- Kate on the schedule for Katherine in HR (nickname)
- one float who appears on both facility pages

**The PDF generator must be parametric** so the chaos deck can mutate it: header text, footnote on/off, cell values, dash style, rows per page, scanned or not.

### Chaos deck (`tests/chaos/`)

- Each mutation is `{id, description, target files, mutate(fn), expect_codes, forbid_codes}`, applied to the clean baseline.
- Each test asserts:
  - the run finishes without exceptions
  - the expected codes are present
  - the forbidden codes are absent (e.g. renamed headers must not produce a BLOCKER)
- `make chaos` writes `reports/chaos_coverage.md` and `.json`; the UI shows the JSON.
- **Pinned date:** fixtures and tests pin `as_of = 2026-09-21` (the day after the sample week), so results never drift with the calendar. At that date the clean set must raise no BLOCKER, CRITICAL, or WARNING flags. Demo runs default to today.
- **Coverage rule:** every P0 code in the rule catalog must be exercised by at least one mutation. The coverage report lists any P0 code with no test; that list must be empty before phase 9 is done.

**Minimum mutations**

*CSV structure*
- M01 renamed headers (synonyms) → no BLOCKER; data identical
- M02 reordered columns → identical results
- M03 extra column → HEADER_UNMAPPED_COLUMN
- M04 payroll hours column dropped → HEADER_REQUIRED_MISSING for payroll only; other sources still processed
- M05 unquoted "LAST, FIRST" → ROW_DELIMITER_REPAIRED; rows recovered
- M06 UTF-8 BOM + CRLF → identical results
- M07 Latin-1 file with an accented name → ENCODING_FALLBACK; name preserved
- M08 tab-delimited → identical results
- M09 blank rows + repeated header + total row → ROW_DROPPED_NONDATA
- M58 unrelated CSV dropped in (e.g. an inventory list) → FILE_TYPE_UNKNOWN for that file only; the four real sources still processed
- M69 truncated row with missing fields → ROW_FIELD_COUNT_MISMATCH; row quarantined, rest of the file processed

*Values*
- M10 Excel serial dates → EXCEL_SERIAL_DATE; correct values
- M11 mixed and ambiguous dates → normalized, plus DATE_AMBIGUOUS_ASSUMED
- M12 impossible date → DATE_IMPOSSIBLE
- M13 phone variants plus one invalid → VALUE_NORMALIZED, plus PHONE_INVALID
- M14 license number variants (no dash, lowercase, missing prefix) → still links
- M15 license prefix contradicts type → LICENSE_PREFIX_TYPE_MISMATCH
- M16 hours "36:30" and "40 hrs" parse; negative → HOURS_NEGATIVE; 200 → HOURS_EXCESSIVE_WEEK
- M52 unknown facility code in payroll ("HVB") → CODE_UNKNOWN_FACILITY
- M53 unknown job code in payroll ("FLT") → CODE_UNKNOWN_ROLE
- M57 free-text date ("spring 2020") → DATE_UNPARSEABLE
- M59 hours written as "forty" → HOURS_UNPARSEABLE

*Identity*
- M17 nickname on schedule → auto-link
- M18 name typo → link (auto or review)
- M19 look-alike names → correct assignment or MATCH_AMBIGUOUS
- M20 payroll person not in HR → UNMATCHED_PAYROLL
- M21 schedule person not in HR → UNMATCHED_SCHEDULE
- M22 duplicate payroll row → DUPLICATE_PAY_PERIOD
- M30 shared license number → LICENSE_NUMBER_SHARED
- M31 employee ID collision → EMPLOYEE_ID_COLLISION
- M32 rehire duplicate → DUPLICATE_PERSON_HR
- M51 HR license number missing from the license service → LICENSE_NOT_IN_SERVICE
- M60 RN in HR with a blank license number and no license row → LICENSED_ROLE_NO_CREDENTIAL
- M61 payroll name "BELL, M." at the other facility (score 7.5) → MATCH_REVIEW
- M62 license under a maiden name (same number, different surname) → NAME_MISMATCH_LICENSE; still linked
- M71 license row for someone not in HR (a former employee) → UNMATCHED_LICENSE

*Cross-source and time*
- M23 paid > scheduled and paid < scheduled → HOURS_VARIANCE (both directions)
- M24 facility conflict → FACILITY_CONFLICT
- M25 role exceeds license → ROLE_EXCEEDS_LICENSE
- M26 HR expiry ≠ license service → HR_LICENSE_EXPIRY_STALE
- M27 expired license with shifts → WORKED_AFTER_EXPIRY
- M28 license expiring mid-week with later shifts → SCHEDULED_AFTER_EXPIRY
- M29 stale verification → VERIFICATION_STALE
- M33 hire date after the pay period → ACTIVITY_BEFORE_HIRE
- M54 payroll covers a different week than the schedule → one COVERAGE_GAP_BETWEEN_SOURCES; forbid SCHEDULED_NOT_PAID and PAID_NOT_SCHEDULED
- M55 license expires after the person's last shift but before the as-of date → CREDENTIAL_EXPIRED; forbid WORKED_AFTER_EXPIRY
- M56 licenses expiring 45 and 10 days after the as-of date → CREDENTIAL_EXPIRING at WARNING and at CRITICAL
- M63 payroll row for an HR person who is on no schedule page → PAID_NOT_SCHEDULED + PBJ_UNALLOCATED_HOURS
- M64 6-day pay period → PAYROLL_PERIOD_INVALID
- M65 one facility-week's paid hours 5% above its shift hours → PBJ_TRACEABILITY_VARIANCE
- M68 RN paid under job code LPN (below the license; HR says RN) → ROLE_CONFLICT; forbid ROLE_EXCEEDS_LICENSE
- M70 person on the schedule with no payroll row in a week payroll covers → SCHEDULED_NOT_PAID

*Schedule PDF*
- M34 en dash and case variants in cells → identical results
- M35 undefined shift (7p-7a) → SHIFT_NOT_IN_FOOTNOTE; 12 h computed
- M36 unparseable cell → SHIFT_UNPARSEABLE
- M37 PTO cell → PTO_ON_SCHEDULE; explains the variance
- M38 overnight 11p-7a → split at midnight in daily_hours
- M39 missing footnote → PDF_FOOTNOTE_MISSING; clock math used
- M40 day with no RN → RN_8H_COVERAGE_GAP
- M41 same person on both pages at overlapping times → OVERLAPPING_SHIFTS
- M42 weekday/date mismatch in a header → WEEKDAY_DATE_MISMATCH
- M43 week spanning 12/28–01/03 → correct years
- M44 table spills onto a second page → all rows captured
- M45 scanned PDF → OCR used, or PDF_NO_TEXT_LAYER; never a crash
- M49 more than 22.5 h in a day → DAILY_HOURS_OVER_CAP
- M66 page header with no recognizable facility name → PDF_FACILITY_UNKNOWN; facility inferred from the staff on the page
- M67 extra page with no table (e.g. a notes page) → PDF_TABLE_NOT_FOUND for that page only; other pages parsed

*Files and combined*
- M46 misleading filenames → correct source detection
- M47 same file uploaded twice → FILE_DUPLICATE; no double counting
- M48 kitchen sink (many mutations at once) → completes; all expected codes present
- M50 CNA expiry not on a month-end → CNA_EXPIRY_NOT_MONTH_END

### Identity accuracy test

A seeded, larger synthetic set (about 60 people, 4 weeks, known ground truth) measures linkage precision and recall. Target: precision ≥ 0.98 on auto-links.

## 22. Trucking pack (reuse proof)

**Sources**

| File | Columns |
|---|---|
| `drivers.csv` | driver_id, first_name, last_name, terminal, phone, cdl_number, cdl_expiration, hire_date |
| `payroll.csv` | Same shape as healthcare payroll; job codes DRV/HLP; terminal codes |
| `credentials.csv` | credential_number, name_on_credential, credential_type (CDL, MED_CERT, HAZMAT), expiration_date, last_verified |
| `dispatch.csv` | driver_name, date, start_time, end_time, terminal, route |

**Rules**
- A driver dispatched without a valid CDL and medical certificate is CRITICAL.
- Expiring windows, as in healthcare.
- Configurable max on-duty hours per day (illustrative).
- The same four-way match.

**Goal.** Switching packs in the UI changes only the source nodes and the rule node; the core nodes stay identical. If trucking seems to need an engine change, generalize the engine instead of special-casing.

## 23. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Demo set ingests in under 5 s on a laptop; 10k payroll rows in under 30 s |
| Robustness | No unhandled exception ever reaches the user |
| Determinism | Determinism and idempotency as in section 2; stable sort orders; seeded generators |
| Offline | No network calls at runtime unless an optional assist feature is enabled |
| Privacy | Data stays local; mask phone and license numbers in logs; CORS limited to localhost |
| Startup | One command; macOS and Linux first, Windows best-effort |
| Code quality | Type hints, ruff, small modules, docstrings on public functions; strict TypeScript; prefer boring, readable code, since judges may read it |

## 24. Build phases

P0 = phases 0–7, P1 = phases 8–10, P2 = phase 11.

| Phase | Build | Done when |
|---|---|---|
| 0. Scaffold | Layout, Makefile, pyproject, Vite app, DuckDB schema, `/api/health` | `make setup && make dev` serves API + UI; `make test` runs |
| 1. Fixtures first | Sample generator incl. parametric schedule PDF; clean / messy / scan sets | Files exist; the PDF visibly matches the described layout |
| 2. Ingestion | Detection, robust reader, contracts, header mapping, quarantine, file flags | Clean set ingests with zero BLOCKER/WARNING; messy set yields the expected file and format flags; reader-quirk unit tests pass |
| 3. Normalizers + PDF adapter | Shift grammar, footnote, year inference, midnight split, bbox capture | Clean PDF parses to exact segments; ≥ 40 shift-grammar unit tests; date, phone, name, and license tests |
| 4. Identity resolution | Scoring with explanations; decisions applied | All clean records link correctly; look-alike and ghost cases produce the expected flags |
| 5. Ledger, golden, four-way match, rules | All P0 rules; flags with evidence and stable IDs | Messy set yields the expected flags with correct severities and messages; the clean set at the pinned as-of date yields nothing above INFO |
| 6. Views, API, CLI | Staffing, expirations, referral; exports; `summary.md` | Exports are correct for the fixtures |
| 7. Frontend P0 | Ingest, live Pipeline canvas, Flags with evidence, People with evidence graph, the three views | The whole demo runs end to end in the browser |
| 8. Decisions loop | Accept/reject match, map code/header, dismiss, re-run; PDF evidence viewer with bbox; safe edits | Resolving a flag and re-running makes it disappear, and the audit log shows why |
| 9. Chaos deck | All mutations; coverage page | Every P0 mutation passes |
| 10. Trucking pack + docs | Pack switcher; README, DECISIONS, DEMO, generated RULES | Pack swap works live |
| 11. Stretch | OCR fallback; optional LLM assist (header-mapping suggestions, vision fallback, plain-English Q&A over golden tables via read-only SQL); run-to-run diff; source quality scorecards | — |

## 25. Deliverables

- **The working app and CLI**, plus `make demo`.
- **`DECISIONS.md`**: two pages at most. This is the written summary for submission. Cover:
  - what we store and why (claims ledger)
  - who wins conflicts (authority matrix)
  - the identity approach, and why not ML
  - never-crash ingestion
  - deterministic rules vs AI
  - time-aware compliance
  - PBJ assumptions (midnight split, meal deduction, attribution)
  - reuse via packs
  - human decisions as memory
  - known limitations
- **`docs/DEMO.md`**: a five-minute script.
  1. Drop in the files cold and watch the canvas light up.
  2. Open the identity graph (Marc → Marcus).
  3. Walk the critical flags.
  4. Resolve one flag and re-run.
  5. Show the three views.
  6. Swap to the trucking pack.
  7. Show chaos coverage.
- **`docs/RULES.md`**: generated from the registry.
- **`README.md`**: setup, run, ingest, and an architecture diagram in Mermaid.

## 26. Working rules for you

- Plan first (`PLAN.md`) and wait for my approval.
- Write tests alongside code and keep `make test` green. Add a test for every bug you fix.
- Never hard-code sample names, IDs, or dates. Derive everything from the data and pack config.
- When something is ambiguous, choose the most robust behavior, note it in `DECISIONS.md`, and keep going. Ask me only about decisions that change scope.
- Stick to the listed dependencies unless one is clearly necessary, and note any addition in `DECISIONS.md`.
- After each phase:
  1. Run the tests and the demo pipeline.
  2. Update `PROGRESS.md` (done / next / risks).
  3. Commit with a clear message.
- If time gets tight, cut phase 11, then 10, then parts of 8. Never cut P0 robustness or the core of the chaos deck.
