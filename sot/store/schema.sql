-- Harborview Source of Truth: storage schema.
--
-- Shape rules, which the rest of the engine relies on:
--   * Derived tables carry run_id in their primary key and are rebuilt wholesale on
--     every run, from the full claims ledger. Nothing is updated in place, so the order
--     files arrived in cannot leak into the result (spec principle 9).
--   * files and decisions are deliberately NOT run-scoped. A landed file is identified
--     by its content, and a human decision is memory that outlives the run that
--     prompted it (spec sections 6 and 16).
--   * Raw values live beside normalized ones everywhere, because a flag is only
--     useful if it can point at the characters that caused it (spec principle 2).
--   * Row numbers follow the spreadsheet convention: header is row 1, first data row
--     is row 2. PDF pages are 1-based (spec section 12).

-- ---------------------------------------------------------------------------
-- Runs and files
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS runs (
    run_id            VARCHAR PRIMARY KEY,
    started_at        TIMESTAMP NOT NULL,
    finished_at       TIMESTAMP,
    status            VARCHAR NOT NULL,      -- RUNNING | OK | DEGRADED | FAILED
    pack              VARCHAR NOT NULL,
    pack_version      VARCHAR,
    as_of             DATE NOT NULL,
    input_digest      VARCHAR NOT NULL,      -- content hash of the inputs, order-free
    decisions_digest  VARCHAR,               -- which decisions were in force
    params_json       VARCHAR,               -- effective params after overrides
    engine_version    VARCHAR NOT NULL,
    duration_ms       BIGINT,
    note              VARCHAR
);

-- Content-addressed registry of everything ever landed. One row per distinct sha256.
CREATE TABLE IF NOT EXISTS files (
    file_id           VARCHAR PRIMARY KEY,
    sha256            VARCHAR NOT NULL,
    original_name     VARCHAR NOT NULL,
    stored_path       VARCHAR NOT NULL,
    size_bytes        BIGINT NOT NULL,
    media_kind        VARCHAR NOT NULL,      -- tabular | pdf | unknown
    detected_source   VARCHAR,               -- hr | payroll | licenses | schedule | ...
    detect_confidence DOUBLE,
    detect_method     VARCHAR,               -- header_signature | pdf | override | learned
    encoding          VARCHAR,
    delimiter         VARCHAR,
    header_row_index  INTEGER,               -- 1-based line holding the header
    page_count        INTEGER,
    first_seen_run    VARCHAR,
    last_seen_run     VARCHAR,
    first_seen_at     TIMESTAMP
);

-- Which files took part in which run, and under what override.
CREATE TABLE IF NOT EXISTS run_files (
    run_id            VARCHAR NOT NULL,
    file_id           VARCHAR NOT NULL,
    source_type       VARCHAR,               -- resolved type used for this run
    type_override     VARCHAR,               -- set when a human forced the type
    is_duplicate      BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_id, file_id)
);

-- Every row as read, raw beside normalized. The evidence viewer reads from here.
CREATE TABLE IF NOT EXISTS raw_rows (
    run_id            VARCHAR NOT NULL,
    file_id           VARCHAR NOT NULL,
    row_index         INTEGER NOT NULL,      -- spreadsheet convention
    raw_json          VARCHAR NOT NULL,      -- {header: raw cell text}
    norm_json         VARCHAR,               -- {canonical column: normalized value}
    quality_json      VARCHAR,               -- {canonical column: ok|repaired|...}
    status            VARCHAR NOT NULL,      -- ok | repaired | quarantined | dropped
    note              VARCHAR,
    PRIMARY KEY (run_id, file_id, row_index)
);

-- Every extracted PDF cell with its geometry, so a flag can highlight the exact box.
CREATE TABLE IF NOT EXISTS pdf_cells (
    run_id            VARCHAR NOT NULL,
    file_id           VARCHAR NOT NULL,
    page              INTEGER NOT NULL,      -- 1-based
    row_index         INTEGER NOT NULL,
    col_index         INTEGER NOT NULL,
    column_header     VARCHAR,
    text              VARCHAR,
    x0                DOUBLE,                -- PDF points, origin top-left
    top               DOUBLE,
    x1                DOUBLE,
    bottom            DOUBLE,
    page_width        DOUBLE,
    page_height       DOUBLE,
    extraction_method VARCHAR,               -- lines | text | words | ocr | vision
    confidence        DOUBLE,
    PRIMARY KEY (run_id, file_id, page, row_index, col_index)
);

-- Rows that could not be trusted into the standardized tables. Never silently dropped.
CREATE TABLE IF NOT EXISTS quarantine (
    run_id            VARCHAR NOT NULL,
    file_id           VARCHAR NOT NULL,
    row_index         INTEGER NOT NULL,
    rule_code         VARCHAR NOT NULL,
    raw_text          VARCHAR,
    field_count       INTEGER,
    expected_count    INTEGER,
    note              VARCHAR,
    PRIMARY KEY (run_id, file_id, row_index, rule_code)
);

-- ---------------------------------------------------------------------------
-- Standardized sources
--
-- One physical table holding every standardized record, keyed by the canonical
-- source role, with the pack-mapped fields in payload_json. Packs differ in their
-- columns; the engine does not, which is what lets the trucking pack reuse every
-- node downstream of ingestion without an engine change (spec section 22).
-- The spec's std_hr / std_payroll / std_licenses names exist as views over it.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS std_records (
    run_id            VARCHAR NOT NULL,
    record_id         VARCHAR NOT NULL,
    source_type       VARCHAR NOT NULL,      -- pack's source name, e.g. hr, drivers
    source_role       VARCHAR NOT NULL,      -- engine role: roster|payroll|credentials|...
    file_id           VARCHAR NOT NULL,
    row_index         INTEGER NOT NULL,
    payload_json      VARCHAR NOT NULL,      -- canonical field -> normalized value
    raw_json          VARCHAR NOT NULL,      -- canonical field -> raw value
    quality_json      VARCHAR,               -- canonical field -> normalizer quality
    person_id         VARCHAR,               -- filled by identity resolution
    PRIMARY KEY (run_id, record_id)
);

CREATE OR REPLACE VIEW std_hr AS
SELECT
    run_id, record_id, file_id, row_index, person_id, source_type,
    json_extract_string(payload_json, '$.employee_id')        AS employee_id,
    json_extract_string(payload_json, '$.first_name')         AS first_name,
    json_extract_string(payload_json, '$.middle_name')        AS middle_name,
    json_extract_string(payload_json, '$.last_name')          AS last_name,
    json_extract_string(payload_json, '$.job_title')          AS job_title,
    json_extract_string(payload_json, '$.job_code')           AS job_code,
    json_extract_string(payload_json, '$.facility')           AS facility,
    json_extract_string(payload_json, '$.facility_code')      AS facility_code,
    json_extract_string(payload_json, '$.phone')              AS phone,
    json_extract_string(payload_json, '$.email')              AS email,
    json_extract_string(payload_json, '$.license_number')     AS license_number,
    TRY_CAST(json_extract_string(payload_json, '$.license_expiration') AS DATE) AS license_expiration,
    TRY_CAST(json_extract_string(payload_json, '$.hire_date') AS DATE)          AS hire_date,
    TRY_CAST(json_extract_string(payload_json, '$.termination_date') AS DATE)   AS termination_date,
    json_extract_string(payload_json, '$.status')             AS status
FROM std_records WHERE source_role = 'roster';

CREATE OR REPLACE VIEW std_payroll AS
SELECT
    run_id, record_id, file_id, row_index, person_id, source_type,
    json_extract_string(payload_json, '$.payroll_id')         AS payroll_id,
    json_extract_string(payload_json, '$.employee_name')      AS employee_name,
    json_extract_string(payload_json, '$.job_code')           AS job_code,
    json_extract_string(payload_json, '$.facility_code')      AS facility_code,
    TRY_CAST(json_extract_string(payload_json, '$.period_start') AS DATE) AS period_start,
    TRY_CAST(json_extract_string(payload_json, '$.period_end') AS DATE)   AS period_end,
    TRY_CAST(json_extract_string(payload_json, '$.hours_paid') AS DOUBLE) AS hours_paid,
    TRY_CAST(json_extract_string(payload_json, '$.hours_worked') AS DOUBLE) AS hours_worked,
    TRY_CAST(json_extract_string(payload_json, '$.pto_hours') AS DOUBLE)  AS pto_hours,
    json_extract_string(payload_json, '$.pay_type')           AS pay_type
FROM std_records WHERE source_role = 'payroll';

CREATE OR REPLACE VIEW std_licenses AS
SELECT
    run_id, record_id, file_id, row_index, person_id, source_type,
    json_extract_string(payload_json, '$.license_number')     AS license_number,
    json_extract_string(payload_json, '$.name_on_license')    AS name_on_license,
    json_extract_string(payload_json, '$.license_type')       AS license_type,
    TRY_CAST(json_extract_string(payload_json, '$.expiration_date') AS DATE) AS expiration_date,
    TRY_CAST(json_extract_string(payload_json, '$.last_verified') AS DATE)   AS last_verified,
    TRY_CAST(json_extract_string(payload_json, '$.issue_date') AS DATE)      AS issue_date,
    json_extract_string(payload_json, '$.status')             AS status,
    json_extract_string(payload_json, '$.state')              AS state
FROM std_records WHERE source_role = 'credentials';

-- Worked/planned time, from any source: a schedule PDF, a dispatch CSV, a timeclock.
CREATE TABLE IF NOT EXISTS shift_segments (
    run_id            VARCHAR NOT NULL,
    segment_id        VARCHAR NOT NULL,
    file_id           VARCHAR NOT NULL,
    source_type       VARCHAR NOT NULL,
    person_ref        VARCHAR,               -- name exactly as the source wrote it
    person_id         VARCHAR,               -- filled by identity resolution
    facility_code     VARCHAR,
    role_code         VARCHAR,
    work_date         DATE,                  -- date the segment starts
    start_ts          TIMESTAMP,
    end_ts            TIMESTAMP,
    hours             DOUBLE,
    category          VARCHAR NOT NULL,      -- WORK | PTO | TRAINING | ONCALL | OFF
    hours_source      VARCHAR,               -- footnote | clock
    page              INTEGER,
    row_index         INTEGER,
    col_index         INTEGER,
    column_header     VARCHAR,
    raw_text          VARCHAR,
    confidence        DOUBLE,
    note              VARCHAR,
    PRIMARY KEY (run_id, segment_id)
);

-- ---------------------------------------------------------------------------
-- Entities and evidence
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS persons (
    run_id            VARCHAR NOT NULL,
    person_id         VARCHAR NOT NULL,
    status            VARCHAR NOT NULL,      -- confirmed | provisional
    display_name      VARCHAR,
    name_key          VARCHAR,               -- folded comparison key
    given             VARCHAR,
    middle            VARCHAR,
    family            VARCHAR,
    suffix            VARCHAR,
    employee_id       VARCHAR,
    home_facility     VARCHAR,
    primary_role      VARCHAR,
    PRIMARY KEY (run_id, person_id)
);

-- One row per source record attached to a person, with the reasoning kept.
CREATE TABLE IF NOT EXISTS links (
    run_id            VARCHAR NOT NULL,
    link_id           VARCHAR NOT NULL,
    person_id         VARCHAR NOT NULL,
    source_type       VARCHAR NOT NULL,
    record_id         VARCHAR NOT NULL,
    fingerprint       VARCHAR,
    score             DOUBLE,
    band              VARCHAR,               -- auto | review | ambiguous | none
    decided_by        VARCHAR NOT NULL,      -- auto | human | anchor
    explanation_json  VARCHAR,               -- per-feature waterfall
    PRIMARY KEY (run_id, link_id)
);

-- The ledger. Nothing is ever overwritten; conflicts live side by side.
CREATE TABLE IF NOT EXISTS claims (
    run_id            VARCHAR NOT NULL,
    claim_id          VARCHAR NOT NULL,
    entity_type       VARCHAR NOT NULL,      -- person | facility | credential | org
    entity_id         VARCHAR NOT NULL,
    attribute         VARCHAR NOT NULL,
    value_raw         VARCHAR,
    value_norm        VARCHAR,
    source_type       VARCHAR NOT NULL,
    file_id           VARCHAR,
    locator_json      VARCHAR,               -- {row,column} or {page,row,column,bbox}
    observed_on       DATE,                  -- the date the source vouches for
    quality           VARCHAR,               -- ok | repaired | ambiguous | invalid
    PRIMARY KEY (run_id, claim_id)
);

CREATE TABLE IF NOT EXISTS golden_attributes (
    run_id            VARCHAR NOT NULL,
    entity_type       VARCHAR NOT NULL,
    entity_id         VARCHAR NOT NULL,
    attribute         VARCHAR NOT NULL,
    value_norm        VARCHAR,
    claim_id          VARCHAR,               -- the winning claim
    rule              VARCHAR,               -- which survivorship step decided it
    source_type       VARCHAR,
    observed_on       DATE,
    candidate_count   INTEGER NOT NULL DEFAULT 1,
    conflict_count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, entity_type, entity_id, attribute)
);

CREATE TABLE IF NOT EXISTS credentials (
    run_id            VARCHAR NOT NULL,
    credential_id     VARCHAR NOT NULL,
    holder_type       VARCHAR NOT NULL,      -- person | org
    holder_id         VARCHAR,
    credential_type   VARCHAR,               -- RN | LPN | CNA | CDL | MED_CERT | ...
    number_norm       VARCHAR,
    number_raw        VARCHAR,
    number_prefix     VARCHAR,
    number_digits     VARCHAR,
    name_on_credential VARCHAR,
    issue_date        DATE,
    expires_on        DATE,
    last_verified     DATE,
    status            VARCHAR,
    state             VARCHAR,
    source_type       VARCHAR,
    file_id           VARCHAR,
    row_index         INTEGER,
    PRIMARY KEY (run_id, credential_id)
);

CREATE TABLE IF NOT EXISTS pay_lines (
    run_id            VARCHAR NOT NULL,
    pay_line_id       VARCHAR NOT NULL,
    person_id         VARCHAR,
    payroll_ref       VARCHAR,
    facility_code     VARCHAR,
    role_code         VARCHAR,
    period_start      DATE,
    period_end        DATE,
    hours_paid        DOUBLE,
    hours_worked      DOUBLE,
    pto_hours         DOUBLE,
    pay_type          VARCHAR,
    file_id           VARCHAR,
    row_index         INTEGER,
    PRIMARY KEY (run_id, pay_line_id)
);

-- ---------------------------------------------------------------------------
-- Match and views
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS match_person_week (
    run_id                VARCHAR NOT NULL,
    person_id             VARCHAR NOT NULL,
    period_start          DATE NOT NULL,
    period_end            DATE,
    facility_code         VARCHAR NOT NULL,
    role_code             VARCHAR NOT NULL,
    scheduled_work_hours  DOUBLE,
    scheduled_pto_hours   DOUBLE,
    paid_hours            DOUBLE,
    delta                 DOUBLE,
    employed              VARCHAR,           -- Tri
    permitted             VARCHAR,           -- Tri
    status                VARCHAR NOT NULL,  -- MATCHED | HOURS_VARIANCE | ...
    direction             VARCHAR,           -- PAID_MORE | PAID_LESS
    explained_by_pto      BOOLEAN NOT NULL DEFAULT FALSE,
    in_both_coverages     BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (run_id, person_id, period_start, facility_code, role_code)
);

CREATE TABLE IF NOT EXISTS match_person_day (
    run_id            VARCHAR NOT NULL,
    person_id         VARCHAR NOT NULL,
    work_date         DATE NOT NULL,
    facility_code     VARCHAR NOT NULL,
    role_code         VARCHAR NOT NULL,
    work_hours        DOUBLE,
    pto_hours         DOUBLE,
    segment_ids_json  VARCHAR,
    credential_valid  VARCHAR,               -- Tri
    employed          VARCHAR,               -- Tri
    has_overlap       BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_id, person_id, work_date, facility_code, role_code)
);

CREATE TABLE IF NOT EXISTS daily_hours (
    run_id            VARCHAR NOT NULL,
    facility_code     VARCHAR NOT NULL,
    work_date         DATE NOT NULL,
    person_id         VARCHAR NOT NULL,
    display_name      VARCHAR,
    role_code         VARCHAR NOT NULL,
    pbj_job_code      VARCHAR,
    scheduled_hours   DOUBLE,                -- after the midnight split
    meal_deduction    DOUBLE,
    pbj_hours         DOUBLE,
    tier              VARCHAR NOT NULL,      -- VERIFIED | CONFLICT | SCHEDULE_ONLY | UNALLOCATED
    evidence_json     VARCHAR,
    PRIMARY KEY (run_id, facility_code, work_date, person_id, role_code)
);

-- ---------------------------------------------------------------------------
-- Flags and decisions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS flags (
    run_id            VARCHAR NOT NULL,
    flag_id           VARCHAR NOT NULL,      -- stable across runs; excludes run_id
    rule_code         VARCHAR NOT NULL,
    severity          VARCHAR NOT NULL,      -- BLOCKER | CRITICAL | WARNING | INFO
    category          VARCHAR NOT NULL,      -- FILE | FORMAT | IDENTITY | CROSS_SOURCE | TIME | PDF | DOMAIN
    title             VARCHAR NOT NULL,
    message           VARCHAR NOT NULL,
    entities_json     VARCHAR,               -- [{type,id,display}]
    suggested_action  VARCHAR,
    owner_role        VARCHAR,               -- HR | PAYROLL | DON | ADMINISTRATOR | DATA_STEWARD
    due_date          DATE,
    status            VARCHAR NOT NULL,      -- OPEN | RESOLVED | DISMISSED
    dismiss_reason    VARCHAR,
    occurrence_count  INTEGER NOT NULL DEFAULT 1,  -- >1 for aggregated INFO flags
    node_id           VARCHAR,
    params_json       VARCHAR,               -- the values the message was built from
    first_seen_run    VARCHAR,
    last_seen_run     VARCHAR,
    PRIMARY KEY (run_id, flag_id)
);

CREATE TABLE IF NOT EXISTS flag_evidence (
    run_id            VARCHAR NOT NULL,
    flag_id           VARCHAR NOT NULL,
    seq               INTEGER NOT NULL,
    file_id           VARCHAR,
    source_type       VARCHAR,
    row_index         INTEGER,
    page              INTEGER,
    column_name       VARCHAR,
    raw_value         VARCHAR,
    x0                DOUBLE,
    top               DOUBLE,
    x1                DOUBLE,
    bottom            DOUBLE,
    PRIMARY KEY (run_id, flag_id, seq)
);

-- Human input, kept outside the run scope: this is the memory of the system.
CREATE TABLE IF NOT EXISTS decisions (
    decision_id       VARCHAR PRIMARY KEY,
    decision_type     VARCHAR NOT NULL,      -- ACCEPT_MATCH | REJECT_MATCH | CODE_MAP | HEADER_MAP | DISMISS_FLAG | NOTE
    key_json          VARCHAR NOT NULL,      -- what it applies to (fingerprint, code, flag id)
    value_json        VARCHAR,               -- what it decides
    actor             VARCHAR,
    reason            VARCHAR,
    created_at        TIMESTAMP NOT NULL,
    active            BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------------
-- Run telemetry
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS node_stats (
    run_id            VARCHAR NOT NULL,
    node_id           VARCHAR NOT NULL,
    node_type         VARCHAR NOT NULL,
    label             VARCHAR,
    status            VARCHAR NOT NULL,      -- ok | degraded | failed | skipped
    rows_in           BIGINT NOT NULL DEFAULT 0,
    rows_out          BIGINT NOT NULL DEFAULT 0,
    quarantined       BIGINT NOT NULL DEFAULT 0,
    flags_blocker     INTEGER NOT NULL DEFAULT 0,
    flags_critical    INTEGER NOT NULL DEFAULT 0,
    flags_warning     INTEGER NOT NULL DEFAULT 0,
    flags_info        INTEGER NOT NULL DEFAULT 0,
    duration_ms       BIGINT,
    started_at        TIMESTAMP,
    finished_at       TIMESTAMP,
    error             VARCHAR,
    PRIMARY KEY (run_id, node_id)
);

-- Append-only event log. Streamed live over SSE and replayable afterwards, which is
-- the demo-day fallback when a live ingest misbehaves (spec section 19).
CREATE TABLE IF NOT EXISTS run_events (
    run_id            VARCHAR NOT NULL,
    seq               BIGINT NOT NULL,
    ts                TIMESTAMP NOT NULL,
    event_type        VARCHAR NOT NULL,      -- node_started | node_progress | node_finished | run_finished
    node_id           VARCHAR,
    payload_json      VARCHAR,
    PRIMARY KEY (run_id, seq)
);
