# Rules

Generated from the rule registry by `make docs`. Do not edit by hand.

82 rules, 81 with an evaluator so far.

Severity means: **BLOCKER** a file or page could not be processed, and only that one is affected · **CRITICAL** compliance, safety, or money is at risk · **WARNING** needs human judgement · **INFO** auto-fixed or informational, aggregated so the inbox stays readable.

## Coverage

| Priority | Rules | With an evaluator |
|---|---|---|
| P0 | 59 | 38 |
| P1 | 22 | 12 |
| P2 | 1 | 0 |

P0 rules still to implement: 0

## File and structure

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `FILE_TYPE_UNKNOWN` | BLOCKER | P0 | DATA_STEWARD | Cannot tell which source a file is; offer an override |
| `HEADER_REQUIRED_MISSING` | BLOCKER | P0 | DATA_STEWARD | Required column missing (that file only) |
| `NODE_FAILED` | BLOCKER | P0 | DATA_STEWARD | A pipeline step raised an unexpected error; downstream steps ran degraded |
| `HEADER_AMBIGUOUS` | WARNING | P1 | DATA_STEWARD | Two columns map to one field |
| `ROW_FIELD_COUNT_MISMATCH` | WARNING | P0 | DATA_STEWARD | Row quarantined |
| `SOURCE_MISSING` | WARNING | P0 | DATA_STEWARD | A source the pack expects was not supplied; checks needing it return unknown |
| `VOLUME_DROP` *(pending)* | WARNING | P2 | DATA_STEWARD | Row count fell more than 30% vs the previous run of the same source |
| `ENCODING_FALLBACK` | INFO | P1 | DATA_STEWARD | File decoded with a fallback encoding |
| `FILE_DUPLICATE` | INFO | P0 | DATA_STEWARD | Same file seen before; not double counted |
| `HEADER_UNMAPPED_COLUMN` | INFO | P0 | DATA_STEWARD | Extra column kept as extra claims |
| `ROW_DELIMITER_REPAIRED` | INFO | P0 | DATA_STEWARD | Unquoted "LAST, FIRST" repaired |
| `ROW_DROPPED_NONDATA` | INFO | P0 | DATA_STEWARD | Blank, header-repeat, total, or notes rows (count) |

## Format

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `LICENSE_PREFIX_TYPE_MISMATCH` | CRITICAL | P0 | HR | License prefix contradicts its type |
| `CODE_UNKNOWN_FACILITY` | WARNING | P0 | DATA_STEWARD | Facility code not in the crosswalk |
| `CODE_UNKNOWN_ROLE` | WARNING | P0 | DATA_STEWARD | Role code not in the crosswalk |
| `DATE_IMPOSSIBLE` | WARNING | P0 | DATA_STEWARD | Date doesn't exist |
| `DATE_UNPARSEABLE` | WARNING | P0 | DATA_STEWARD | Date couldn't be read |
| `HOURS_EXCESSIVE_WEEK` | WARNING† | P0 | PAYROLL | Implausible weekly hours |
| `HOURS_NEGATIVE` | WARNING | P0 | PAYROLL | Negative hours; possibly a reversal |
| `HOURS_UNPARSEABLE` | WARNING | P0 | PAYROLL | Hours couldn't be read |
| `PHONE_INVALID` | WARNING | P0 | HR | Phone number invalid |
| `DATE_AMBIGUOUS_ASSUMED` | INFO | P1 | DATA_STEWARD | Day/month order assumed |
| `EXCEL_SERIAL_DATE` | INFO | P1 | DATA_STEWARD | Excel serial converted |
| `LICENSE_NUMBER_CHAR_CONFUSION` | INFO | P1 | DATA_STEWARD | O/0 or I/L/1 substitution applied |
| `NULL_TOKEN` | INFO | P1 | DATA_STEWARD | Null tokens found (aggregated) |
| `VALUE_NORMALIZED` | INFO | P0 | DATA_STEWARD | Values reformatted (aggregated) |

† Severity depends on context:

- `HOURS_EXCESSIVE_WEEK` — CRITICAL above 168 hours, which is longer than a week; WARNING above 80.

## Identity

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `EMPLOYEE_ID_COLLISION` | CRITICAL | P0 | HR | One ID, two different people |
| `LICENSE_NUMBER_SHARED` | CRITICAL | P0 | HR | One credential number on two people |
| `UNMATCHED_PAYROLL` | CRITICAL | P0 | PAYROLL | Paid but not in HR: a ghost-employee red flag, or unrecorded agency staff |
| `DUPLICATE_PERSON_HR` | WARNING | P0 | HR | Same person under two HR IDs |
| `DUPLICATE_SCHEDULE_ROW` | WARNING | P1 | DON | Person listed twice on one page |
| `LICENSE_NOT_IN_SERVICE` | WARNING† | P0 | HR | HR lists a license number the verification service doesn't have |
| `MATCH_AMBIGUOUS` | WARNING | P0 | DATA_STEWARD | Top two candidates too close |
| `MATCH_REVIEW` | WARNING | P0 | DATA_STEWARD | Score in the review band |
| `NAME_MISMATCH_LICENSE` | WARNING | P0 | HR | Linked by number but names differ (maiden name?) |
| `SHARED_PHONE` | WARNING | P1 | HR | Two people share a phone number |
| `UNMATCHED_LICENSE` | WARNING | P0 | HR | License row matches no person |
| `UNMATCHED_SCHEDULE` | WARNING† | P0 | DON | Scheduled but not in HR |

† Severity depends on context:

- `LICENSE_NOT_IN_SERVICE` — CRITICAL when the person worked a licensed role in the period.
- `UNMATCHED_SCHEDULE` — CRITICAL when the role requires a credential, otherwise WARNING.

## Cross-source (the four-way match)

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `DUPLICATE_PAY_PERIOD` | CRITICAL | P0 | PAYROLL | Possible double pay |
| `LICENSED_ROLE_NO_CREDENTIAL` | CRITICAL | P0 | HR | Licensed role with no credential |
| `OVERLAPPING_SHIFTS` | CRITICAL | P0 | DON | Same person in two places at once |
| `ROLE_EXCEEDS_LICENSE` | CRITICAL | P0 | DON | Any role claim is above what the credential allows: scope of practice, and the wrong PBJ code |
| `FACILITY_CONFLICT` | WARNING | P0 | DATA_STEWARD | Systems disagree on facility; PBJ hours follow where the work happened |
| `HOURS_VARIANCE` | WARNING† | P0 | PAYROLL | Paid and scheduled hours differ beyond tolerance |
| `HR_LICENSE_EXPIRY_STALE` | WARNING | P0 | HR | HR's copy of the expiry disagrees with the license service |
| `PAID_NOT_SCHEDULED` | WARNING | P0 | PAYROLL | Paid hours with no scheduled shifts |
| `PAYROLL_PERIOD_INVALID` | WARNING | P0 | PAYROLL | Period isn't 7 days, doesn't start on the pack's week start, or ends before it starts |
| `ROLE_CONFLICT` | WARNING | P0 | HR | Systems disagree on role |
| `SCHEDULED_NOT_PAID` | WARNING | P0 | PAYROLL | Scheduled shifts with no pay |
| `COVERAGE_GAP_BETWEEN_SOURCES` | INFO | P0 | ADMINISTRATOR | Sources cover different periods |

† Severity depends on context:

- `HOURS_VARIANCE` — INFO when the difference is accounted for by paid leave on the rota.

## Time

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `ACTIVITY_BEFORE_HIRE` | CRITICAL | P0 | HR | Paid or scheduled before the hire date |
| `DAILY_HOURS_OVER_CAP` | CRITICAL | P0 | ADMINISTRATOR | Over the daily cap; PBJ would reject it |
| `SCHEDULED_AFTER_EXPIRY` | CRITICAL | P0 | DON | Forecast: scheduled after expiry |
| `WORKED_AFTER_EXPIRY` | CRITICAL | P0 | DON | Worked after the credential expired, judged as of the shift date |
| `CREDENTIAL_EXPIRED` | WARNING† | P0 | HR | Credential already expired |
| `CREDENTIAL_EXPIRING` | WARNING† | P0 | HR | Expiry approaching |
| `HIRE_DATE_IN_FUTURE` | WARNING | P1 | HR | Hire date is in the future |
| `LONG_DAY` | WARNING | P1 | DON | Day longer than the fatigue limit |
| `VERIFICATION_STALE` | WARNING | P0 | HR | last_verified older than verification_max_age_days |
| `VERIFIED_DATE_IN_FUTURE` | WARNING | P1 | DATA_STEWARD | Verification date is in the future |
| `WEEKDAY_DATE_MISMATCH` | WARNING | P0 | DON | Schedule weekday doesn't match its date |
| `CONSECUTIVE_DAYS` | INFO | P1 | DON | Too many days in a row |
| `SHORT_REST` | INFO | P1 | DON | Too little rest between shifts |

† Severity depends on context:

- `CREDENTIAL_EXPIRED` — CRITICAL when the person is still working in a role that needs it.
- `CREDENTIAL_EXPIRING` — CRITICAL inside 30 days, WARNING inside 90.

## Schedule PDF

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `PDF_NO_TEXT_LAYER` | BLOCKER† | P0 | DATA_STEWARD | Scanned page |
| `PDF_TABLE_NOT_FOUND` | BLOCKER | P0 | DATA_STEWARD | No table could be extracted |
| `PDF_FACILITY_UNKNOWN` | WARNING† | P0 | DATA_STEWARD | Page facility not recognized |
| `PDF_FOOTNOTE_MISSING` | WARNING | P0 | DON | No shift-length note; clock math used |
| `SHIFT_UNPARSEABLE` | WARNING | P0 | DON | Cell couldn't be read |
| `FOOTNOTE_CLOCK_MISMATCH` | INFO | P1 | DON | Footnote hours differ from clock math |
| `PERSON_ON_MULTIPLE_PAGES` | INFO | P1 | DON | Legitimate float across facilities |
| `PTO_ON_SCHEDULE` | INFO | P0 | DON | Paid time off on the schedule |
| `SHIFT_AMBIGUOUS_ASSUMED` | INFO | P1 | DON | Ambiguous shift mapped using the footnote |
| `SHIFT_NOT_IN_FOOTNOTE` | INFO | P0 | DON | Hours computed from clock times |
| `SHIFT_SPANS_PERIOD` | INFO | P1 | DON | Shift runs past the period end |

† Severity depends on context:

- `PDF_NO_TEXT_LAYER` — INFO when OCR read the page; BLOCKER for that page otherwise.
- `PDF_FACILITY_UNKNOWN` — WARNING when the facility can be inferred from the staff listed; BLOCKER for that page when it cannot.

## Domain

| Code | Severity | Pri | Owner | Meaning |
|---|---|---|---|---|
| `HPRD_BELOW_MINIMUM` | CRITICAL | P1 | ADMINISTRATOR | Below hours-per-resident-day minimums (only when census is provided) |
| `RN_8H_COVERAGE_GAP` | CRITICAL | P0 | DON | A facility-day inside schedule coverage without RN coverage for 8 consecutive hours |
| `CNA_HOURS_EXCLUDED_UNCERTIFIED` | WARNING | P1 | ADMINISTRATOR | CNA hours on dates without valid certification are excluded from the CNA bucket |
| `CNA_RECERT_EVIDENCE_INSUFFICIENT` | WARNING | P1 | HR | Fewer than the required paid aide hours inside the recert window in the available payroll |
| `PBJ_TRACEABILITY_VARIANCE` | WARNING | P0 | ADMINISTRATOR | Per facility-period, schedule-derived worked hours and paid hours (minus PTO) differ by more than the configured percentage |
| `PBJ_UNALLOCATED_HOURS` | WARNING | P0 | ADMINISTRATOR | Paid hours with no schedule day; never invent days |
| `ZERO_RN_DAYS_QUARTER` | WARNING† | P1 | ADMINISTRATOR | Count of zero-RN days per facility per quarter |
| `CNA_EXPIRY_NOT_MONTH_END` | INFO | P1 | HR | Likely data-entry error; NY CNA renewals fall on month-ends |

† Severity depends on context:

- `ZERO_RN_DAYS_QUARTER` — CRITICAL at the configured critical threshold, WARNING at the warn threshold.

## Messages

What each rule says, with the values filled in at the time.

**`DUPLICATE_PAY_PERIOD`** — Paid twice for the same week

> {display_name} has {count} payroll rows for {facility} as {role} covering {period_start} to {period_end} ({rows}), totalling {total_hours} hours.

*Action:* Confirm whether this is a correction or a duplicate payment.

**`LICENSED_ROLE_NO_CREDENTIAL`** — Licensed role with no credential on file

> {display_name} works as {role} at {facility}, which requires {required}, but no credential is on file in any source.

*Action:* Obtain and verify the credential, or reassign until it is on file.

**`OVERLAPPING_SHIFTS`** — In two places at once

> {display_name} is scheduled at {first_facility} {first_window} and at {second_facility} {second_window} on {work_date}. Both cannot be true.

*Action:* Correct the rota; one of the two shifts is somebody else's.

**`ROLE_EXCEEDS_LICENSE`** — Working above their credential

> {display_name} is recorded as {claimed_role} in {source_label}, but holds only {held_credentials}. That is outside their scope of practice and reports these hours under the wrong category.

*Action:* Stop the assignment and verify the credential before the next shift.

**`FACILITY_CONFLICT`** — Systems disagree on the site

> {display_name} is recorded at {values}. Reported hours follow the schedule, because that is where the work happened.

*Action:* Correct whichever system is out of date.

**`HOURS_VARIANCE`** — Paid and scheduled hours disagree

> {display_name} at {facility}, week of {period_start}: paid {paid_hours} hours against {scheduled_hours} scheduled, a difference of {delta}. {explanation}

*Action:* Reconcile the timesheet against the rota for that week.

**`HR_LICENSE_EXPIRY_STALE`** — HR's expiry date is out of date

> The roster says {display_name}'s {credential_type} expires {hr_date}; the verification service says {service_date}. The service is treated as authoritative.

*Action:* Update the roster from the verification service.

**`PAID_NOT_SCHEDULED`** — Paid with no shifts on the rota

> {display_name} was paid {paid_hours} hours at {facility} for {period_start} to {period_end}, but has no shifts on the schedule for that week.

*Action:* Check whether the shifts were worked off-rota or the payment is wrong.

**`PAYROLL_PERIOD_INVALID`** — Pay period looks wrong

> Payroll row {record_label} covers {period_start} to {period_end}: {problem}. Weekly comparisons for this row may be misleading.

*Action:* Check the pay period on the export.

**`ROLE_CONFLICT`** — Systems disagree on the role

> {display_name} is recorded as {values}. The difference changes which staffing category these hours are reported under.

*Action:* Agree the role and correct the other systems.

**`SCHEDULED_NOT_PAID`** — Worked the rota but was not paid

> {display_name} has {scheduled_hours} scheduled hours at {facility} for {period_start} to {period_end}, and no payroll row for that week.

*Action:* Check whether the shifts were covered by someone else, or the pay was missed.

**`COVERAGE_GAP_BETWEEN_SOURCES`** — Sources cover different periods

> The schedule covers {schedule_range} and payroll covers {payroll_range}. Only the overlap has been compared; {excluded} period(s) were left out rather than flagged.

*Action:* Export both systems over the same period for a complete comparison.

**`HPRD_BELOW_MINIMUM`** — Below the staffing minimum

> {facility} is below the {bucket} staffing minimum on {days} day(s). The worst is {work_date}, at {actual:.2f} hours per resident against a {minimum} minimum with {residents} residents.

*Action:* Review cover for that day. Compliance is assessed quarterly against census.
 · *Configured by:* `hprd_minimums`

**`RN_8H_COVERAGE_GAP`** — No registered nurse on duty

> {facility} has no RN on duty for {required} consecutive hours on {work_date} ({actual}). Federal rules require an RN on duty {required} consecutive hours a day, seven days a week.

*Action:* Cover the gap, and check whether the rota omits someone who was actually there.
 · *Configured by:* `rn_min_consecutive_hours`, `rn_coverage_mode`

**`CNA_HOURS_EXCLUDED_UNCERTIFIED`** — Aide hours excluded from reported staffing

> {hours} of {display_name}'s aide hours at {facility} fall on dates with no valid certification and are excluded from the aide total. Only certified aide hours count.

*Action:* Verify the certification covering those dates.

**`CNA_RECERT_EVIDENCE_INSUFFICIENT`** — Not enough paid hours on file to recertify

> {display_name} has {found_hours} paid aide hours in the payroll available for the {window_months} months before {expires_on}; {required_hours} are needed to recertify. The employer files the renewal.

*Action:* Check payroll outside this export, then file the renewal.
 · *Configured by:* `cna_recert.period_months`, `cna_recert.min_paid_hours`

**`PBJ_TRACEABILITY_VARIANCE`** — Reported hours would not survive an audit

> {facility} for {period_start} to {period_end}: {scheduled_hours} schedule-derived hours against {paid_hours} paid, a gap of {variance_pct:.1f}% against a {threshold}% tolerance. Audits compare submissions to payroll.

*Action:* Reconcile the rota against payroll before submitting.
 · *Configured by:* `pbj.traceability_variance_pct`

**`PBJ_UNALLOCATED_HOURS`** — Paid hours that cannot be reported by day

> {hours} paid hours at {facility} for {period_start} to {period_end} have no matching schedule day, so they cannot be reported by date. Days have not been invented for them.

*Action:* Supply timekeeping data for those hours, or correct the rota.

**`ZERO_RN_DAYS_QUARTER`** — Days with no RN hours this quarter

> {facility} has {days} day(s) with no RN hours in {quarter}. Seven or more has long meant a one-star staffing rating.

*Action:* Review cover for those days before the quarter closes.
 · *Configured by:* `zero_rn_days.warn`, `zero_rn_days.critical`

**`CNA_EXPIRY_NOT_MONTH_END`** — Aide certification expires mid-month

> {display_name}'s certification is recorded as expiring {expires_on}, which is not a month end. New York aide renewals fall on the last day of the month.

*Action:* Check the date against the certificate.
 · *Configured by:* `cna_recert.expiry_on_month_end`

**`FILE_TYPE_UNKNOWN`** — Unrecognised file

> {filename} does not match any known source closely enough to classify (best guess {best_source} at {best_score:.0%} confidence, below the {threshold:.0%} threshold). Nothing from this file has been used.

*Action:* Pick the correct source type for this file, or remove it if it does not belong.

**`HEADER_REQUIRED_MISSING`** — Required column missing

> {filename} is missing the required column {column} ({source} data). The rest of the upload has been processed; this file has not.

*Action:* Re-export the file with the missing column, or map an existing column to it.

**`NODE_FAILED`** — Processing step failed

> The {label} step failed with {error}. Steps after it ran with whatever data was available and are marked degraded, so some findings may be missing.

*Action:* This is a bug. The run log has the traceback.

**`HEADER_AMBIGUOUS`** — Two columns claim the same field

> In {filename}, both {columns} map to {field}. {chosen} was used because it matched more closely.

*Action:* Confirm which column is correct and map the other explicitly.

**`ROW_FIELD_COUNT_MISMATCH`** — Row has the wrong number of fields

> Row {row_index} of {filename} has {found} fields where {expected} were expected, and could not be repaired. It has been quarantined, not dropped.

*Action:* Check the row in the source file; a stray or missing delimiter is the usual cause.

**`SOURCE_MISSING`** — A source is missing

> No {role} data was supplied, so {consequence} Checks that need it are reported as unknown rather than guessed at.

*Action:* Upload the missing export and re-run.

**`VOLUME_DROP`** — Far fewer rows than last time

> {source} has {current} rows, down {drop:.0%} from {previous} in the previous run. A partial export is the usual cause.

*Action:* Check the export covered the whole period before relying on these numbers.

**`ENCODING_FALLBACK`** — File was not UTF-8

> {filename} is not valid UTF-8; it was decoded as {encoding}. Accented characters have been preserved, but check any name that looks wrong.

*Action:* Re-export as UTF-8 if names look mangled.

**`FILE_DUPLICATE`** — Duplicate file ignored

> {filename} is byte-for-byte identical to {original_name}, already ingested. It has not been counted twice.

*Action:* No action needed. Remove the duplicate upload if it was accidental.

**`HEADER_UNMAPPED_COLUMN`** — Unrecognised columns kept

> {count} column(s) in {filename} did not match anything in the {source} contract ({columns}). The values have been kept as evidence but are not used in any rule.

*Action:* Map the column to a known field if it matters, or ignore it.

**`ROW_DELIMITER_REPAIRED`** — Rows repaired after an unquoted comma

> {count} row(s) in {filename} had a name containing the delimiter without quotes (for example {example}). The fields were rejoined and the rows kept.

*Action:* No action needed. Quoting the name column on export would avoid it.

**`ROW_DROPPED_NONDATA`** — Non-data rows skipped

> {count} row(s) in {filename} were not data ({breakdown}) and were skipped.

*Action:* No action needed.

**`LICENSE_PREFIX_TYPE_MISMATCH`** — Credential number contradicts its type

> Credential {number} is recorded as type {credential_type}, but its prefix says {prefix_type}. One of the two is wrong, and which one changes who may work.

*Action:* Verify the credential with the issuing service and correct the record.

**`CODE_UNKNOWN_FACILITY`** — Unknown facility code

> {count} row(s) in {filename} use the facility code {code!r}, which is not in the crosswalk. Those hours are not counted against any facility.

*Action:* Map the code to a facility, or correct it at source.

**`CODE_UNKNOWN_ROLE`** — Unknown job code

> {count} row(s) in {filename} use the job code {code!r}, which is not in the crosswalk. Those hours are not attributed to a staffing category.

*Action:* Map the code to a role, or correct it at source.

**`DATE_IMPOSSIBLE`** — Date that does not exist

> {column} in row {row_index} of {filename} reads {raw_value!r}, which is not a real date. The field is empty for this record.

*Action:* Correct the date in the source file.

**`DATE_UNPARSEABLE`** — Unreadable date

> {column} in row {row_index} of {filename} reads {raw_value!r}, which is not a date. The field is empty for this record, so any check that needs it is unknown.

*Action:* Correct the date in the source file.

**`HOURS_EXCESSIVE_WEEK`** — Implausible weekly hours

> {display_name} is paid {hours} hours for the week of {period_start}. {note}

*Action:* Check for a duplicated row or a decimal point in the wrong place.

**`HOURS_NEGATIVE`** — Negative hours

> Row {row_index} of {filename} pays {hours} hours. A negative figure is usually a correction to an earlier period rather than an error.

*Action:* Confirm this is a reversal, and that the original row is also in the data.

**`HOURS_UNPARSEABLE`** — Unreadable hours

> {column} in row {row_index} of {filename} reads {raw_value!r}, which is not a number of hours. This record contributes nothing to the totals.

*Action:* Correct the value in payroll.

**`PHONE_INVALID`** — Phone number is not usable

> {display_name}'s phone number reads {raw_value!r}, which is not a usable number.

*Action:* Correct the number in HR.

**`DATE_AMBIGUOUS_ASSUMED`** — Day and month order assumed

> {count} date(s) in {column} of {filename} could be read either way round (for example {example}). {order} was assumed, from {basis}.

*Action:* Confirm the date order used by the exporting system.

**`EXCEL_SERIAL_DATE`** — Spreadsheet date numbers converted

> {count} value(s) in {column} of {filename} were Excel date serials (for example {example} became {converted}).

*Action:* No action needed. Formatting the column as a date before export would avoid it.

**`LICENSE_NUMBER_CHAR_CONFUSION`** — Credential number read with a letter-digit swap

> {count} credential number(s) matched only after treating look-alike characters as digits (for example {example} read as {converted}).

*Action:* Confirm the number with the issuing service if the match matters.

**`NULL_TOKEN`** — Placeholder values treated as blank

> {count} cell(s) in {filename} held a placeholder rather than a value ({tokens}). They are treated as missing.

*Action:* No action needed, unless a placeholder was meant to be a real value.

**`VALUE_NORMALIZED`** — Values tidied up

> {count} value(s) in {column} of {filename} were reformatted on the way in (for example {example}). The original text is kept as evidence.

*Action:* No action needed.

**`EMPLOYEE_ID_COLLISION`** — One employee number, two people

> Employee number {employee_id} is used by both {first_name} and {second_name}. Every figure attributed to that number is unreliable.

*Action:* Issue a new number to one of them and re-export.

**`LICENSE_NUMBER_SHARED`** — One credential, two holders

> Credential {number} is recorded against both {first_name} and {second_name}. At most one of them is licensed.

*Action:* Verify with the issuing service and correct the record for whoever is wrong.

**`UNMATCHED_PAYROLL`** — Paid, but in no other system

> Payroll row {record_label} pays {name!r} {hours} hours at {facility} for {period_start} to {period_end}, but no matching person exists in the roster.

*Action:* Confirm whether this is agency staff, a leaver, or a payment that should not have been made.

**`DUPLICATE_PERSON_HR`** — One person, two employee records

> {display_name} appears twice in the roster, as {first_id} and {second_id}, sharing {shared}. A rehire is the usual reason.

*Action:* Merge the records, or confirm they are two different people.

**`DUPLICATE_SCHEDULE_ROW`** — Listed twice on one page

> {display_name} appears {count} times on the {facility} page. Hours from the extra row(s) are not counted twice.

*Action:* Remove the duplicate row from the schedule.

**`LICENSE_NOT_IN_SERVICE`** — Credential not found at the verification service

> The roster lists credential {number} for {display_name}, but the verification service has no record of it.{work_note}

*Action:* Verify the credential directly with the issuing body.

**`MATCH_AMBIGUOUS`** — Two people match equally well

> {source_label} record {record_label} matches both {first_name} (score {first_score}) and {second_name} (score {second_score}). It has not been linked to either.

*Action:* Pick the right person, or reject both if it is somebody else.

**`MATCH_REVIEW`** — Possible match, needs a human

> {source_label} record {record_label} looks like {display_name} (score {score}, review band {low}-{high}), but not confidently enough to link automatically.

*Action:* Accept or reject the match. The decision is remembered for future runs.

**`NAME_MISMATCH_LICENSE`** — Credential is under a different name

> Credential {number} matches {display_name} by number, but the service has it under {name_on_credential!r}. A name change is the usual reason.

*Action:* Confirm the name change and update whichever record is out of date.

**`SHARED_PHONE`** — Two people share a phone number

> {first_name} and {second_name} both have the phone number {phone}. Household members, or one record copied from the other.

*Action:* Confirm they are two people and correct the number if not.

**`UNMATCHED_LICENSE`** — Credential belongs to nobody on the roster

> Credential {number} ({credential_type}) is held by {name!r}, who is not in the roster. A former employee is the usual reason.

*Action:* Confirm the holder has left, or add them to the roster.

**`UNMATCHED_SCHEDULE`** — On the rota, but in no other system

> {name!r} appears on the {facility} schedule with {shift_count} shift(s), but is not in the roster.{credential_note}

*Action:* Add them to the roster, or confirm they are agency staff and record the agency.

**`PDF_NO_TEXT_LAYER`** — Scanned page with no readable text

> Page {page} of {filename} is an image with no text layer.{ocr_note}

*Action:* Export the schedule as a PDF rather than scanning a printout.

**`PDF_TABLE_NOT_FOUND`** — No timetable on this page

> No schedule table could be found on page {page} of {filename}. Other pages were processed normally.

*Action:* Check the page is part of the schedule; a cover or notes page is harmless.

**`PDF_FACILITY_UNKNOWN`** — Page does not name a known facility

> Page {page} of {filename} does not name a facility in the crosswalk. {resolution}

*Action:* Add the facility name to the crosswalk, or title the page with it.

**`PDF_FOOTNOTE_MISSING`** — No shift-length note on the page

> Page {page} of {filename} has no note defining shift lengths, so hours were computed from the clock times. A shift with an unpaid break will read long.

*Action:* Add the shift-length note to the printed schedule.

**`SHIFT_UNPARSEABLE`** — Unreadable shift

> {display_name}'s cell for {column_header} on page {page} reads {raw_value!r}, which is not a shift or a known absence code. No hours counted for that day.

*Action:* Correct the cell, or add the code to the pack if it is a real absence type.

**`FOOTNOTE_CLOCK_MISMATCH`** — Footnote and clock disagree

> The footnote says {token} is {footnote_hours} hours; the clock says {clock_hours}. The footnote has been used, as it accounts for breaks.

*Action:* No action needed unless the footnote is wrong.

**`PERSON_ON_MULTIPLE_PAGES`** — Works at more than one site

> {display_name} appears on {page_count} facility pages ({facilities}). Hours are reported against the site where each shift was worked.

*Action:* No action needed.

**`PTO_ON_SCHEDULE`** — Paid leave on the rota

> {count} cell(s) on the schedule record paid leave rather than a shift ({codes}). Those hours are paid but not worked, and are excluded from reported staffing.

*Action:* No action needed.

**`SHIFT_AMBIGUOUS_ASSUMED`** — Shift without am/pm resolved from the footnote

> {count} cell(s) give times without am or pm (for example {example}); they were matched to {resolved} from the shifts the footnote defines.

*Action:* Write shifts as 7a-3p on the printed schedule to remove the ambiguity.

**`SHIFT_NOT_IN_FOOTNOTE`** — Shift length taken from the clock

> {count} shift(s) on page {page} are not defined in the footnote (for example {example}), so their length was computed from the clock times.

*Action:* Add the shift to the footnote if it is a standard pattern.

**`SHIFT_SPANS_PERIOD`** — Shift runs past the end of the period

> {display_name}'s {token} on {work_date} runs to {end_ts}, past the end of the period. Hours are attributed to the day the shift started.

*Action:* No action needed.

**`ACTIVITY_BEFORE_HIRE`** — Working before they were hired

> {display_name} was hired {hire_date} but has {activity} dated {activity_date}, before that. Either the hire date or the activity is wrong.

*Action:* Correct the hire date, or confirm the earlier work was under a previous record.

**`DAILY_HOURS_OVER_CAP`** — More hours in a day than reporting allows

> {display_name} has {hours} hours on {work_date}, above the {cap} hour daily cap. A submission containing this would be rejected.

*Action:* Check for a duplicated shift or an overnight counted twice.
 · *Configured by:* `pbj.daily_cap_hours`

**`SCHEDULED_AFTER_EXPIRY`** — Scheduled after their credential expires

> {display_name}'s {credential_type} expires {expires_on}, and they are scheduled for {shift_count} shift(s) at {facility} after that ({dates}).

*Action:* Renew before the first of those shifts, or re-cover them.

**`WORKED_AFTER_EXPIRY`** — Worked after their credential expired

> {display_name}'s {credential_type} expired {expires_on}, and they worked {shift_count} shift(s) at {facility} after that date ({dates}).

*Action:* Those hours may not count towards reported staffing. Verify the renewal.

**`CREDENTIAL_EXPIRED`** — Credential has expired

> {display_name}'s {credential_type} ({number}) expired {expires_on}, {days_ago} days before the as-of date.{work_note}

*Action:* Renew before the next shift in a licensed role.

**`CREDENTIAL_EXPIRING`** — Credential expiring soon

> {display_name}'s {credential_type} ({number}) expires {expires_on}, {days_left} days from the as-of date.{recert_note}

*Action:* Start the renewal now; the filing usually sits with the employer.

**`HIRE_DATE_IN_FUTURE`** — Hired in the future

> {display_name}'s hire date is {hire_date}, after the as-of date of {as_of}.

*Action:* Correct the hire date, or confirm this is a future starter.

**`LONG_DAY`** — Very long day

> {display_name} worked {hours} hours on {work_date}, beyond the {limit} hour fatigue limit.

*Action:* Review the rota for that day.
 · *Configured by:* `fatigue.long_day_hours`

**`VERIFICATION_STALE`** — Credential not checked recently

> {display_name}'s {credential_type} was last verified {last_verified}, {age_days} days ago. The policy is {max_age_days} days.

*Action:* Re-run verification with the issuing service.
 · *Configured by:* `verification_max_age_days`

**`VERIFIED_DATE_IN_FUTURE`** — Verified in the future

> {display_name}'s {credential_type} is recorded as verified on {last_verified}, which is after the as-of date of {as_of}.

*Action:* Correct the verification date.

**`WEEKDAY_DATE_MISMATCH`** — Weekday and date disagree

> The {facility} schedule heads a column {header!r}, but {parsed_date} is a {actual_weekday}. The date has been trusted.

*Action:* Correct the schedule heading before it is posted again.

**`CONSECUTIVE_DAYS`** — Many days worked in a row

> {display_name} worked {days} days in a row from {start_date}. The guideline is {limit}.

*Action:* Review the rota.
 · *Configured by:* `fatigue.max_consecutive_days`

**`SHORT_REST`** — Short rest between shifts

> {display_name} finished at {previous_end} and started again at {next_start}, {rest_hours} hours later. The guideline is {min_rest}.

*Action:* Review the rota.
 · *Configured by:* `fatigue.min_rest_hours`
