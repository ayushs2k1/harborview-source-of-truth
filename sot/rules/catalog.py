"""The rule catalog: spec section 13, as data.

Every code the system can emit is declared here, including ones whose evaluator has
not been written yet. Declaring them early is deliberate: it makes ``docs/RULES.md``
complete, gives the chaos deck a list of codes to demand coverage of, and turns
"which P0 rules are still missing" into a query instead of a memory exercise.

Message templates are filled with real values at the call site. They are written the
way the spec's examples are written - names, dates, and numbers in the sentence, so
the reader does not have to open the file to understand what happened.
"""

from __future__ import annotations

from typing import Any

from sot.rules.model import Aggregate, Category, OwnerRole, Severity
from sot.rules.registry import RuleRegistry, RuleSpec

S, C, OWN, A = Severity, Category, OwnerRole, Aggregate


def _rule(
    code: str,
    severity: Severity,
    category: Category,
    priority: str,
    meaning: str,
    title: str,
    message: str,
    action: str,
    owner: OwnerRole,
    **kwargs: Any,
) -> RuleSpec:
    return RuleSpec(
        code=code,
        severity=severity,
        category=category,
        priority=priority,
        meaning=meaning,
        title=title,
        message=message,
        suggested_action=action,
        owner_role=owner,
        **kwargs,
    )


# --- Conditional severities -------------------------------------------------
# Kept as named functions rather than lambdas so the generated docs can explain
# themselves and a failing case has something readable in the traceback.


def _worse_if(params: dict[str, Any], key: str, worse: Severity, otherwise: Severity) -> Severity:
    return worse if params.get(key) else otherwise


def _severity_unmatched_schedule(params: dict[str, Any]) -> Severity:
    """Someone unknown on the rota is a staffing note, unless the role needs a licence."""
    return _worse_if(params, "role_requires_credential", S.CRITICAL, S.WARNING)


def _severity_license_not_in_service(params: dict[str, Any]) -> Severity:
    return _worse_if(params, "worked_licensed_role", S.CRITICAL, S.WARNING)


def _severity_hours_excessive(params: dict[str, Any]) -> Severity:
    """Over 168 hours in a week is not an error of degree; the week is 168 hours long."""
    return S.CRITICAL if float(params.get("hours", 0) or 0) > 168 else S.WARNING


def _severity_hours_variance(params: dict[str, Any]) -> Severity:
    return S.INFO if params.get("explained_by_pto") else S.WARNING


def _severity_credential_expiring(params: dict[str, Any]) -> Severity:
    days = params.get("days_left")
    return S.CRITICAL if days is not None and int(days) <= 30 else S.WARNING


def _severity_credential_expired(params: dict[str, Any]) -> Severity:
    return _worse_if(params, "active_in_licensed_role", S.CRITICAL, S.WARNING)


def _severity_zero_rn_days(params: dict[str, Any]) -> Severity:
    days = int(params.get("days", 0) or 0)
    return S.CRITICAL if days >= int(params.get("critical_threshold", 7)) else S.WARNING


def _severity_pdf_no_text_layer(params: dict[str, Any]) -> Severity:
    """A scanned page is only a blocker if we could not read it some other way."""
    return S.INFO if params.get("ocr_used") else S.BLOCKER


def _severity_pdf_facility_unknown(params: dict[str, Any]) -> Severity:
    return S.WARNING if params.get("inferred_facility") else S.BLOCKER


# --- File and structure -----------------------------------------------------

FILE_RULES = [
    _rule(
        "FILE_TYPE_UNKNOWN",
        S.BLOCKER,
        C.FILE,
        "P0",
        "Cannot tell which source a file is; offer an override",
        "Unrecognised file",
        "{filename} does not match any known source closely enough to classify "
        "(best guess {best_source} at {best_score:.0%} confidence, below the {threshold:.0%} "
        "threshold). Nothing from this file has been used.",
        "Pick the correct source type for this file, or remove it if it does not belong.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "FILE_DUPLICATE",
        S.INFO,
        C.FILE,
        "P0",
        "Same file seen before; not double counted",
        "Duplicate file ignored",
        "{filename} is byte-for-byte identical to {original_name}, already ingested. "
        "It has not been counted twice.",
        "No action needed. Remove the duplicate upload if it was accidental.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "HEADER_REQUIRED_MISSING",
        S.BLOCKER,
        C.FILE,
        "P0",
        "Required column missing (that file only)",
        "Required column missing",
        "{filename} is missing the required column {column} ({source} data). "
        "The rest of the upload has been processed; this file has not.",
        "Re-export the file with the missing column, or map an existing column to it.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "HEADER_UNMAPPED_COLUMN",
        S.INFO,
        C.FILE,
        "P0",
        "Extra column kept as extra claims",
        "Unrecognised columns kept",
        "{count} column(s) in {filename} did not match anything in the {source} contract "
        "({columns}). The values have been kept as evidence but are not used in any rule.",
        "Map the column to a known field if it matters, or ignore it.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "HEADER_AMBIGUOUS",
        S.WARNING,
        C.FILE,
        "P1",
        "Two columns map to one field",
        "Two columns claim the same field",
        "In {filename}, both {columns} map to {field}. {chosen} was used because it "
        "matched more closely.",
        "Confirm which column is correct and map the other explicitly.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "ROW_FIELD_COUNT_MISMATCH",
        S.WARNING,
        C.FILE,
        "P0",
        "Row quarantined",
        "Row has the wrong number of fields",
        "Row {row_index} of {filename} has {found} fields where {expected} were expected, "
        "and could not be repaired. It has been quarantined, not dropped.",
        "Check the row in the source file; a stray or missing delimiter is the usual cause.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "ROW_DELIMITER_REPAIRED",
        S.INFO,
        C.FILE,
        "P0",
        'Unquoted "LAST, FIRST" repaired',
        "Rows repaired after an unquoted comma",
        "{count} row(s) in {filename} had a name containing the delimiter without quotes "
        "(for example {example}). The fields were rejoined and the rows kept.",
        "No action needed. Quoting the name column on export would avoid it.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "ROW_DROPPED_NONDATA",
        S.INFO,
        C.FILE,
        "P0",
        "Blank, header-repeat, total, or notes rows (count)",
        "Non-data rows skipped",
        "{count} row(s) in {filename} were not data ({breakdown}) and were skipped.",
        "No action needed.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "ENCODING_FALLBACK",
        S.INFO,
        C.FILE,
        "P1",
        "File decoded with a fallback encoding",
        "File was not UTF-8",
        "{filename} is not valid UTF-8; it was decoded as {encoding}. Accented characters "
        "have been preserved, but check any name that looks wrong.",
        "Re-export as UTF-8 if names look mangled.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "VOLUME_DROP",
        S.WARNING,
        C.FILE,
        "P2",
        "Row count fell more than 30% vs the previous run of the same source",
        "Far fewer rows than last time",
        "{source} has {current} rows, down {drop:.0%} from {previous} in the previous run. "
        "A partial export is the usual cause.",
        "Check the export covered the whole period before relying on these numbers.",
        OWN.DATA_STEWARD,
    ),
    _rule(
        "SOURCE_MISSING",
        S.WARNING,
        C.FILE,
        "P0",
        "A source the pack expects was not supplied; checks needing it return unknown",
        "A source is missing",
        "No {role} data was supplied, so {consequence} Checks that need it are reported "
        "as unknown rather than guessed at.",
        "Upload the missing export and re-run.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "NODE_FAILED",
        S.BLOCKER,
        C.FILE,
        "P0",
        "A pipeline step raised an unexpected error; downstream steps ran degraded",
        "Processing step failed",
        "The {label} step failed with {error}. Steps after it ran with whatever data was "
        "available and are marked degraded, so some findings may be missing.",
        "This is a bug. The run log has the traceback.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
]

# --- Format -----------------------------------------------------------------

FORMAT_RULES = [
    _rule(
        "VALUE_NORMALIZED",
        S.INFO,
        C.FORMAT,
        "P0",
        "Values reformatted (aggregated)",
        "Values tidied up",
        "{count} value(s) in {column} of {filename} were reformatted on the way in "
        "(for example {example}). The original text is kept as evidence.",
        "No action needed.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_COLUMN,
        implemented=True,
    ),
    _rule(
        "NULL_TOKEN",
        S.INFO,
        C.FORMAT,
        "P1",
        "Null tokens found (aggregated)",
        "Placeholder values treated as blank",
        "{count} cell(s) in {filename} held a placeholder rather than a value "
        "({tokens}). They are treated as missing.",
        "No action needed, unless a placeholder was meant to be a real value.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "DATE_UNPARSEABLE",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Date couldn't be read",
        "Unreadable date",
        "{column} in row {row_index} of {filename} reads {raw_value!r}, which is not a date. "
        "The field is empty for this record, so any check that needs it is unknown.",
        "Correct the date in the source file.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "DATE_IMPOSSIBLE",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Date doesn't exist",
        "Date that does not exist",
        "{column} in row {row_index} of {filename} reads {raw_value!r}, which is not a real "
        "date. The field is empty for this record.",
        "Correct the date in the source file.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "DATE_AMBIGUOUS_ASSUMED",
        S.INFO,
        C.FORMAT,
        "P1",
        "Day/month order assumed",
        "Day and month order assumed",
        "{count} date(s) in {column} of {filename} could be read either way round "
        "(for example {example}). {order} was assumed, from {basis}.",
        "Confirm the date order used by the exporting system.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_COLUMN,
        implemented=True,
    ),
    _rule(
        "EXCEL_SERIAL_DATE",
        S.INFO,
        C.FORMAT,
        "P1",
        "Excel serial converted",
        "Spreadsheet date numbers converted",
        "{count} value(s) in {column} of {filename} were Excel date serials "
        "(for example {example} became {converted}).",
        "No action needed. Formatting the column as a date before export would avoid it.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_COLUMN,
        implemented=True,
    ),
    _rule(
        "PHONE_INVALID",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Phone number invalid",
        "Phone number is not usable",
        "{display_name}'s phone number reads {raw_value!r}, which is not a usable number.",
        "Correct the number in HR.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "LICENSE_PREFIX_TYPE_MISMATCH",
        S.CRITICAL,
        C.FORMAT,
        "P0",
        "License prefix contradicts its type",
        "Credential number contradicts its type",
        "Credential {number} is recorded as type {credential_type}, but its prefix says "
        "{prefix_type}. One of the two is wrong, and which one changes who may work.",
        "Verify the credential with the issuing service and correct the record.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "LICENSE_NUMBER_CHAR_CONFUSION",
        S.INFO,
        C.FORMAT,
        "P1",
        "O/0 or I/L/1 substitution applied",
        "Credential number read with a letter-digit swap",
        "{count} credential number(s) matched only after treating look-alike characters as "
        "digits (for example {example} read as {converted}).",
        "Confirm the number with the issuing service if the match matters.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "HOURS_UNPARSEABLE",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Hours couldn't be read",
        "Unreadable hours",
        "{column} in row {row_index} of {filename} reads {raw_value!r}, which is not a number "
        "of hours. This record contributes nothing to the totals.",
        "Correct the value in payroll.",
        OWN.PAYROLL,
        implemented=True,
    ),
    _rule(
        "HOURS_NEGATIVE",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Negative hours; possibly a reversal",
        "Negative hours",
        "Row {row_index} of {filename} pays {hours} hours. A negative figure is usually a "
        "correction to an earlier period rather than an error.",
        "Confirm this is a reversal, and that the original row is also in the data.",
        OWN.PAYROLL,
        implemented=True,
    ),
    _rule(
        "HOURS_EXCESSIVE_WEEK",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Implausible weekly hours",
        "Implausible weekly hours",
        "{display_name} is paid {hours} hours for the week of {period_start}. {note}",
        "Check for a duplicated row or a decimal point in the wrong place.",
        OWN.PAYROLL,
        severity_fn=_severity_hours_excessive,
        severity_note="CRITICAL above 168 hours, which is longer than a week; WARNING above 80.",
    ),
    _rule(
        "CODE_UNKNOWN_FACILITY",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Facility code not in the crosswalk",
        "Unknown facility code",
        "{count} row(s) in {filename} use the facility code {code!r}, which is not in the "
        "crosswalk. Those hours are not counted against any facility.",
        "Map the code to a facility, or correct it at source.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_COLUMN,
        implemented=True,
    ),
    _rule(
        "CODE_UNKNOWN_ROLE",
        S.WARNING,
        C.FORMAT,
        "P0",
        "Role code not in the crosswalk",
        "Unknown job code",
        "{count} row(s) in {filename} use the job code {code!r}, which is not in the "
        "crosswalk. Those hours are not attributed to a staffing category.",
        "Map the code to a role, or correct it at source.",
        OWN.DATA_STEWARD,
        aggregate=A.BY_COLUMN,
        implemented=True,
    ),
]

# --- Identity ---------------------------------------------------------------

IDENTITY_RULES = [
    _rule(
        "MATCH_REVIEW",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "Score in the review band",
        "Possible match, needs a human",
        "{source_label} record {record_label} looks like {display_name} (score {score}, "
        "review band {low}-{high}), but not confidently enough to link automatically.",
        "Accept or reject the match. The decision is remembered for future runs.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "MATCH_AMBIGUOUS",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "Top two candidates too close",
        "Two people match equally well",
        "{source_label} record {record_label} matches both {first_name} (score {first_score}) "
        "and {second_name} (score {second_score}). It has not been linked to either.",
        "Pick the right person, or reject both if it is somebody else.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "UNMATCHED_PAYROLL",
        S.CRITICAL,
        C.IDENTITY,
        "P0",
        "Paid but not in HR: a ghost-employee red flag, or unrecorded agency staff",
        "Paid, but in no other system",
        "Payroll row {record_label} pays {name!r} {hours} hours at {facility} for "
        "{period_start} to {period_end}, but no matching person exists in the roster.",
        "Confirm whether this is agency staff, a leaver, or a payment that should not "
        "have been made.",
        OWN.PAYROLL,
        implemented=True,
    ),
    _rule(
        "UNMATCHED_SCHEDULE",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "Scheduled but not in HR",
        "On the rota, but in no other system",
        "{name!r} appears on the {facility} schedule with {shift_count} shift(s), but is not "
        "in the roster.{credential_note}",
        "Add them to the roster, or confirm they are agency staff and record the agency.",
        OWN.DON,
        severity_fn=_severity_unmatched_schedule,
        severity_note="CRITICAL when the role requires a credential, otherwise WARNING.",
        implemented=True,
    ),
    _rule(
        "UNMATCHED_LICENSE",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "License row matches no person",
        "Credential belongs to nobody on the roster",
        "Credential {number} ({credential_type}) is held by {name!r}, who is not in the "
        "roster. A former employee is the usual reason.",
        "Confirm the holder has left, or add them to the roster.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "LICENSE_NOT_IN_SERVICE",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "HR lists a license number the verification service doesn't have",
        "Credential not found at the verification service",
        "The roster lists credential {number} for {display_name}, but the verification "
        "service has no record of it.{work_note}",
        "Verify the credential directly with the issuing body.",
        OWN.HR,
        severity_fn=_severity_license_not_in_service,
        severity_note="CRITICAL when the person worked a licensed role in the period.",
        implemented=True,
    ),
    _rule(
        "DUPLICATE_PERSON_HR",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "Same person under two HR IDs",
        "One person, two employee records",
        "{display_name} appears twice in the roster, as {first_id} and {second_id}, "
        "sharing {shared}. A rehire is the usual reason.",
        "Merge the records, or confirm they are two different people.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "EMPLOYEE_ID_COLLISION",
        S.CRITICAL,
        C.IDENTITY,
        "P0",
        "One ID, two different people",
        "One employee number, two people",
        "Employee number {employee_id} is used by both {first_name} and {second_name}. "
        "Every figure attributed to that number is unreliable.",
        "Issue a new number to one of them and re-export.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "LICENSE_NUMBER_SHARED",
        S.CRITICAL,
        C.IDENTITY,
        "P0",
        "One credential number on two people",
        "One credential, two holders",
        "Credential {number} is recorded against both {first_name} and {second_name}. "
        "At most one of them is licensed.",
        "Verify with the issuing service and correct the record for whoever is wrong.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "NAME_MISMATCH_LICENSE",
        S.WARNING,
        C.IDENTITY,
        "P0",
        "Linked by number but names differ (maiden name?)",
        "Credential is under a different name",
        "Credential {number} matches {display_name} by number, but the service has it under "
        "{name_on_credential!r}. A name change is the usual reason.",
        "Confirm the name change and update whichever record is out of date.",
        OWN.HR,
        implemented=True,
    ),
    _rule(
        "DUPLICATE_SCHEDULE_ROW",
        S.WARNING,
        C.IDENTITY,
        "P1",
        "Person listed twice on one page",
        "Listed twice on one page",
        "{display_name} appears {count} times on the {facility} page. Hours from the extra "
        "row(s) are not counted twice.",
        "Remove the duplicate row from the schedule.",
        OWN.DON,
        implemented=True,
    ),
    _rule(
        "SHARED_PHONE",
        S.WARNING,
        C.IDENTITY,
        "P1",
        "Two people share a phone number",
        "Two people share a phone number",
        "{first_name} and {second_name} both have the phone number {phone}. Household "
        "members, or one record copied from the other.",
        "Confirm they are two people and correct the number if not.",
        OWN.HR,
        implemented=True,
    ),
]

# --- Cross-source (the four-way match) --------------------------------------

CROSS_SOURCE_RULES = [
    _rule(
        "COVERAGE_GAP_BETWEEN_SOURCES",
        S.INFO,
        C.CROSS_SOURCE,
        "P0",
        "Sources cover different periods",
        "Sources cover different periods",
        "The schedule covers {schedule_range} and payroll covers {payroll_range}. Only the "
        "overlap has been compared; {excluded} period(s) were left out rather than flagged.",
        "Export both systems over the same period for a complete comparison.",
        OWN.ADMINISTRATOR,
        implemented=False,
    ),
    _rule(
        "PAID_NOT_SCHEDULED",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "Paid hours with no scheduled shifts",
        "Paid with no shifts on the rota",
        "{display_name} was paid {paid_hours} hours at {facility} for {period_start} to "
        "{period_end}, but has no shifts on the schedule for that week.",
        "Check whether the shifts were worked off-rota or the payment is wrong.",
        OWN.PAYROLL,
    ),
    _rule(
        "SCHEDULED_NOT_PAID",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "Scheduled shifts with no pay",
        "Worked the rota but was not paid",
        "{display_name} has {scheduled_hours} scheduled hours at {facility} for "
        "{period_start} to {period_end}, and no payroll row for that week.",
        "Check whether the shifts were covered by someone else, or the pay was missed.",
        OWN.PAYROLL,
    ),
    _rule(
        "HOURS_VARIANCE",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "Paid and scheduled hours differ beyond tolerance",
        "Paid and scheduled hours disagree",
        "{display_name} at {facility}, week of {period_start}: paid {paid_hours} hours "
        "against {scheduled_hours} scheduled, a difference of {delta}. {explanation}",
        "Reconcile the timesheet against the rota for that week.",
        OWN.PAYROLL,
        severity_fn=_severity_hours_variance,
        severity_note="INFO when the difference is accounted for by paid leave on the rota.",
    ),
    _rule(
        "FACILITY_CONFLICT",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "Systems disagree on facility; PBJ hours follow where the work happened",
        "Systems disagree on the site",
        "{display_name} is recorded at {values}. Reported hours follow the schedule, "
        "because that is where the work happened.",
        "Correct whichever system is out of date.",
        OWN.DATA_STEWARD,
    ),
    _rule(
        "ROLE_CONFLICT",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "Systems disagree on role",
        "Systems disagree on the role",
        "{display_name} is recorded as {values}. The difference changes which staffing "
        "category these hours are reported under.",
        "Agree the role and correct the other systems.",
        OWN.HR,
    ),
    _rule(
        "ROLE_EXCEEDS_LICENSE",
        S.CRITICAL,
        C.CROSS_SOURCE,
        "P0",
        "Any role claim is above what the credential allows: scope of practice, and the "
        "wrong PBJ code",
        "Working above their credential",
        "{display_name} is recorded as {claimed_role} in {source_label}, but holds only "
        "{held_credentials}. That is outside their scope of practice and reports these "
        "hours under the wrong category.",
        "Stop the assignment and verify the credential before the next shift.",
        OWN.DON,
    ),
    _rule(
        "LICENSED_ROLE_NO_CREDENTIAL",
        S.CRITICAL,
        C.CROSS_SOURCE,
        "P0",
        "Licensed role with no credential",
        "Licensed role with no credential on file",
        "{display_name} works as {role} at {facility}, which requires {required}, but no "
        "credential is on file in any source.",
        "Obtain and verify the credential, or reassign until it is on file.",
        OWN.HR,
    ),
    _rule(
        "HR_LICENSE_EXPIRY_STALE",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "HR's copy of the expiry disagrees with the license service",
        "HR's expiry date is out of date",
        "The roster says {display_name}'s {credential_type} expires {hr_date}; the "
        "verification service says {service_date}. The service is treated as authoritative.",
        "Update the roster from the verification service.",
        OWN.HR,
    ),
    _rule(
        "DUPLICATE_PAY_PERIOD",
        S.CRITICAL,
        C.CROSS_SOURCE,
        "P0",
        "Possible double pay",
        "Paid twice for the same week",
        "{display_name} has {count} payroll rows for {facility} as {role} covering "
        "{period_start} to {period_end} ({rows}), totalling {total_hours} hours.",
        "Confirm whether this is a correction or a duplicate payment.",
        OWN.PAYROLL,
        implemented=True,
    ),
    _rule(
        "PAYROLL_PERIOD_INVALID",
        S.WARNING,
        C.CROSS_SOURCE,
        "P0",
        "Period isn't 7 days, doesn't start on the pack's week start, or ends before it starts",
        "Pay period looks wrong",
        "Payroll row {record_label} covers {period_start} to {period_end}: {problem}. "
        "Weekly comparisons for this row may be misleading.",
        "Check the pay period on the export.",
        OWN.PAYROLL,
    ),
    _rule(
        "OVERLAPPING_SHIFTS",
        S.CRITICAL,
        C.CROSS_SOURCE,
        "P0",
        "Same person in two places at once",
        "In two places at once",
        "{display_name} is scheduled at {first_facility} {first_window} and at "
        "{second_facility} {second_window} on {work_date}. Both cannot be true.",
        "Correct the rota; one of the two shifts is somebody else's.",
        OWN.DON,
    ),
]

# --- Time -------------------------------------------------------------------

TIME_RULES = [
    _rule(
        "WORKED_AFTER_EXPIRY",
        S.CRITICAL,
        C.TIME,
        "P0",
        "Worked after the credential expired, judged as of the shift date",
        "Worked after their credential expired",
        "{display_name}'s {credential_type} expired {expires_on}, and they worked "
        "{shift_count} shift(s) at {facility} after that date ({dates}).",
        "Those hours may not count towards reported staffing. Verify the renewal.",
        OWN.DON,
    ),
    _rule(
        "SCHEDULED_AFTER_EXPIRY",
        S.CRITICAL,
        C.TIME,
        "P0",
        "Forecast: scheduled after expiry",
        "Scheduled after their credential expires",
        "{display_name}'s {credential_type} expires {expires_on}, and they are scheduled for "
        "{shift_count} shift(s) at {facility} after that ({dates}).",
        "Renew before the first of those shifts, or re-cover them.",
        OWN.DON,
    ),
    _rule(
        "CREDENTIAL_EXPIRING",
        S.WARNING,
        C.TIME,
        "P0",
        "Expiry approaching",
        "Credential expiring soon",
        "{display_name}'s {credential_type} ({number}) expires {expires_on}, {days_left} days "
        "from the as-of date.{recert_note}",
        "Start the renewal now; the filing usually sits with the employer.",
        OWN.HR,
        severity_fn=_severity_credential_expiring,
        severity_note="CRITICAL inside 30 days, WARNING inside 90.",
    ),
    _rule(
        "CREDENTIAL_EXPIRED",
        S.WARNING,
        C.TIME,
        "P0",
        "Credential already expired",
        "Credential has expired",
        "{display_name}'s {credential_type} ({number}) expired {expires_on}, {days_ago} days "
        "before the as-of date.{work_note}",
        "Renew before the next shift in a licensed role.",
        OWN.HR,
        severity_fn=_severity_credential_expired,
        severity_note="CRITICAL when the person is still working in a role that needs it.",
    ),
    _rule(
        "VERIFICATION_STALE",
        S.WARNING,
        C.TIME,
        "P0",
        "last_verified older than verification_max_age_days",
        "Credential not checked recently",
        "{display_name}'s {credential_type} was last verified {last_verified}, "
        "{age_days} days ago. The policy is {max_age_days} days.",
        "Re-run verification with the issuing service.",
        OWN.HR,
        params_from_pack=("verification_max_age_days",),
    ),
    _rule(
        "VERIFIED_DATE_IN_FUTURE",
        S.WARNING,
        C.TIME,
        "P1",
        "Verification date is in the future",
        "Verified in the future",
        "{display_name}'s {credential_type} is recorded as verified on {last_verified}, which "
        "is after the as-of date of {as_of}.",
        "Correct the verification date.",
        OWN.DATA_STEWARD,
    ),
    _rule(
        "ACTIVITY_BEFORE_HIRE",
        S.CRITICAL,
        C.TIME,
        "P0",
        "Paid or scheduled before the hire date",
        "Working before they were hired",
        "{display_name} was hired {hire_date} but has {activity} dated {activity_date}, "
        "before that. Either the hire date or the activity is wrong.",
        "Correct the hire date, or confirm the earlier work was under a previous record.",
        OWN.HR,
    ),
    _rule(
        "HIRE_DATE_IN_FUTURE",
        S.WARNING,
        C.TIME,
        "P1",
        "Hire date is in the future",
        "Hired in the future",
        "{display_name}'s hire date is {hire_date}, after the as-of date of {as_of}.",
        "Correct the hire date, or confirm this is a future starter.",
        OWN.HR,
    ),
    _rule(
        "WEEKDAY_DATE_MISMATCH",
        S.WARNING,
        C.TIME,
        "P0",
        "Schedule weekday doesn't match its date",
        "Weekday and date disagree",
        "The {facility} schedule heads a column {header!r}, but {parsed_date} is a "
        "{actual_weekday}. The date has been trusted.",
        "Correct the schedule heading before it is posted again.",
        OWN.DON,
        implemented=True,
    ),
    _rule(
        "DAILY_HOURS_OVER_CAP",
        S.CRITICAL,
        C.TIME,
        "P0",
        "Over the daily cap; PBJ would reject it",
        "More hours in a day than reporting allows",
        "{display_name} has {hours} hours on {work_date}, above the {cap} hour daily cap. "
        "A submission containing this would be rejected.",
        "Check for a duplicated shift or an overnight counted twice.",
        OWN.ADMINISTRATOR,
        params_from_pack=("pbj.daily_cap_hours",),
    ),
    _rule(
        "LONG_DAY",
        S.WARNING,
        C.TIME,
        "P1",
        "Day longer than the fatigue limit",
        "Very long day",
        "{display_name} worked {hours} hours on {work_date}, beyond the {limit} hour "
        "fatigue limit.",
        "Review the rota for that day.",
        OWN.DON,
        params_from_pack=("fatigue.long_day_hours",),
    ),
    _rule(
        "SHORT_REST",
        S.INFO,
        C.TIME,
        "P1",
        "Too little rest between shifts",
        "Short rest between shifts",
        "{display_name} finished at {previous_end} and started again at {next_start}, "
        "{rest_hours} hours later. The guideline is {min_rest}.",
        "Review the rota.",
        OWN.DON,
        params_from_pack=("fatigue.min_rest_hours",),
    ),
    _rule(
        "CONSECUTIVE_DAYS",
        S.INFO,
        C.TIME,
        "P1",
        "Too many days in a row",
        "Many days worked in a row",
        "{display_name} worked {days} days in a row from {start_date}. The guideline is {limit}.",
        "Review the rota.",
        OWN.DON,
        params_from_pack=("fatigue.max_consecutive_days",),
    ),
]

# --- Schedule PDF -----------------------------------------------------------

PDF_RULES = [
    _rule(
        "PDF_NO_TEXT_LAYER",
        S.BLOCKER,
        C.PDF,
        "P0",
        "Scanned page",
        "Scanned page with no readable text",
        "Page {page} of {filename} is an image with no text layer.{ocr_note}",
        "Export the schedule as a PDF rather than scanning a printout.",
        OWN.DATA_STEWARD,
        severity_fn=_severity_pdf_no_text_layer,
        severity_note="INFO when OCR read the page; BLOCKER for that page otherwise.",
        implemented=True,
    ),
    _rule(
        "PDF_TABLE_NOT_FOUND",
        S.BLOCKER,
        C.PDF,
        "P0",
        "No table could be extracted",
        "No timetable on this page",
        "No schedule table could be found on page {page} of {filename}. Other pages were "
        "processed normally.",
        "Check the page is part of the schedule; a cover or notes page is harmless.",
        OWN.DATA_STEWARD,
        implemented=True,
    ),
    _rule(
        "PDF_FACILITY_UNKNOWN",
        S.WARNING,
        C.PDF,
        "P0",
        "Page facility not recognized",
        "Page does not name a known facility",
        "Page {page} of {filename} does not name a facility in the crosswalk. {resolution}",
        "Add the facility name to the crosswalk, or title the page with it.",
        OWN.DATA_STEWARD,
        severity_fn=_severity_pdf_facility_unknown,
        severity_note="WARNING when the facility can be inferred from the staff listed; "
        "BLOCKER for that page when it cannot.",
        implemented=True,
    ),
    _rule(
        "PDF_FOOTNOTE_MISSING",
        S.WARNING,
        C.PDF,
        "P0",
        "No shift-length note; clock math used",
        "No shift-length note on the page",
        "Page {page} of {filename} has no note defining shift lengths, so hours were "
        "computed from the clock times. A shift with an unpaid break will read long.",
        "Add the shift-length note to the printed schedule.",
        OWN.DON,
        implemented=True,
    ),
    _rule(
        "SHIFT_UNPARSEABLE",
        S.WARNING,
        C.PDF,
        "P0",
        "Cell couldn't be read",
        "Unreadable shift",
        "{display_name}'s cell for {column_header} on page {page} reads {raw_value!r}, which "
        "is not a shift or a known absence code. No hours counted for that day.",
        "Correct the cell, or add the code to the pack if it is a real absence type.",
        OWN.DON,
        implemented=True,
    ),
    _rule(
        "SHIFT_NOT_IN_FOOTNOTE",
        S.INFO,
        C.PDF,
        "P0",
        "Hours computed from clock times",
        "Shift length taken from the clock",
        "{count} shift(s) on page {page} are not defined in the footnote (for example "
        "{example}), so their length was computed from the clock times.",
        "Add the shift to the footnote if it is a standard pattern.",
        OWN.DON,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "PTO_ON_SCHEDULE",
        S.INFO,
        C.PDF,
        "P0",
        "Paid time off on the schedule",
        "Paid leave on the rota",
        "{count} cell(s) on the schedule record paid leave rather than a shift "
        "({codes}). Those hours are paid but not worked, and are excluded from reported "
        "staffing.",
        "No action needed.",
        OWN.DON,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "FOOTNOTE_CLOCK_MISMATCH",
        S.INFO,
        C.PDF,
        "P1",
        "Footnote hours differ from clock math",
        "Footnote and clock disagree",
        "The footnote says {token} is {footnote_hours} hours; the clock says "
        "{clock_hours}. The footnote has been used, as it accounts for breaks.",
        "No action needed unless the footnote is wrong.",
        OWN.DON,
        implemented=True,
    ),
    _rule(
        "SHIFT_AMBIGUOUS_ASSUMED",
        S.INFO,
        C.PDF,
        "P1",
        "Ambiguous shift mapped using the footnote",
        "Shift without am/pm resolved from the footnote",
        "{count} cell(s) give times without am or pm (for example {example}); they were "
        "matched to {resolved} from the shifts the footnote defines.",
        "Write shifts as 7a-3p on the printed schedule to remove the ambiguity.",
        OWN.DON,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "SHIFT_SPANS_PERIOD",
        S.INFO,
        C.PDF,
        "P1",
        "Shift runs past the period end",
        "Shift runs past the end of the period",
        "{display_name}'s {token} on {work_date} runs to {end_ts}, past the end of the "
        "period. Hours are attributed to the day the shift started.",
        "No action needed.",
        OWN.DON,
        aggregate=A.BY_FILE,
        implemented=True,
    ),
    _rule(
        "PERSON_ON_MULTIPLE_PAGES",
        S.INFO,
        C.PDF,
        "P1",
        "Legitimate float across facilities",
        "Works at more than one site",
        "{display_name} appears on {page_count} facility pages ({facilities}). Hours are "
        "reported against the site where each shift was worked.",
        "No action needed.",
        OWN.DON,
        implemented=True,
    ),
]

# --- Domain: healthcare, New York -------------------------------------------

DOMAIN_RULES = [
    _rule(
        "RN_8H_COVERAGE_GAP",
        S.CRITICAL,
        C.DOMAIN,
        "P0",
        "A facility-day inside schedule coverage without RN coverage for 8 consecutive hours",
        "No registered nurse on duty",
        "{facility} has no RN on duty for {required} consecutive hours on {work_date} "
        "({actual}). Federal rules require an RN on duty {required} consecutive hours a day, "
        "seven days a week.",
        "Cover the gap, and check whether the rota omits someone who was actually there.",
        OWN.DON,
        params_from_pack=("rn_min_consecutive_hours", "rn_coverage_mode"),
    ),
    _rule(
        "PBJ_UNALLOCATED_HOURS",
        S.WARNING,
        C.DOMAIN,
        "P0",
        "Paid hours with no schedule day; never invent days",
        "Paid hours that cannot be reported by day",
        "{hours} paid hours at {facility} for {period_start} to {period_end} have no "
        "matching schedule day, so they cannot be reported by date. Days have not been "
        "invented for them.",
        "Supply timekeeping data for those hours, or correct the rota.",
        OWN.ADMINISTRATOR,
    ),
    _rule(
        "PBJ_TRACEABILITY_VARIANCE",
        S.WARNING,
        C.DOMAIN,
        "P0",
        "Per facility-period, schedule-derived worked hours and paid hours (minus PTO) "
        "differ by more than the configured percentage",
        "Reported hours would not survive an audit",
        "{facility} for {period_start} to {period_end}: {scheduled_hours} schedule-derived "
        "hours against {paid_hours} paid, a gap of {variance_pct:.1f}% against a {threshold}% "
        "tolerance. Audits compare submissions to payroll.",
        "Reconcile the rota against payroll before submitting.",
        OWN.ADMINISTRATOR,
        params_from_pack=("pbj.traceability_variance_pct",),
    ),
    _rule(
        "ZERO_RN_DAYS_QUARTER",
        S.WARNING,
        C.DOMAIN,
        "P1",
        "Count of zero-RN days per facility per quarter",
        "Days with no RN hours this quarter",
        "{facility} has {days} day(s) with no RN hours in {quarter}. Seven or more has long "
        "meant a one-star staffing rating.",
        "Review cover for those days before the quarter closes.",
        OWN.ADMINISTRATOR,
        severity_fn=_severity_zero_rn_days,
        severity_note="CRITICAL at the configured critical threshold, WARNING at the warn "
        "threshold.",
        params_from_pack=("zero_rn_days.warn", "zero_rn_days.critical"),
    ),
    _rule(
        "CNA_EXPIRY_NOT_MONTH_END",
        S.INFO,
        C.DOMAIN,
        "P1",
        "Likely data-entry error; NY CNA renewals fall on month-ends",
        "Aide certification expires mid-month",
        "{display_name}'s certification is recorded as expiring {expires_on}, which is not a "
        "month end. New York aide renewals fall on the last day of the month.",
        "Check the date against the certificate.",
        OWN.HR,
        params_from_pack=("cna_recert.expiry_on_month_end",),
    ),
    _rule(
        "CNA_RECERT_EVIDENCE_INSUFFICIENT",
        S.WARNING,
        C.DOMAIN,
        "P1",
        "Fewer than the required paid aide hours inside the recert window in the available payroll",
        "Not enough paid hours on file to recertify",
        "{display_name} has {found_hours} paid aide hours in the payroll available for the "
        "{window_months} months before {expires_on}; {required_hours} are needed to "
        "recertify. The employer files the renewal.",
        "Check payroll outside this export, then file the renewal.",
        OWN.HR,
        params_from_pack=("cna_recert.period_months", "cna_recert.min_paid_hours"),
    ),
    _rule(
        "CNA_HOURS_EXCLUDED_UNCERTIFIED",
        S.WARNING,
        C.DOMAIN,
        "P1",
        "CNA hours on dates without valid certification are excluded from the CNA bucket",
        "Aide hours excluded from reported staffing",
        "{hours} of {display_name}'s aide hours at {facility} fall on dates with no valid "
        "certification and are excluded from the aide total. Only certified aide hours count.",
        "Verify the certification covering those dates.",
        OWN.ADMINISTRATOR,
    ),
    _rule(
        "HPRD_BELOW_MINIMUM",
        S.CRITICAL,
        C.DOMAIN,
        "P1",
        "Below hours-per-resident-day minimums (only when census is provided)",
        "Below the staffing minimum",
        "{facility} on {work_date}: {bucket} staffing is {actual:.2f} hours per resident "
        "against a {minimum} minimum, with {residents} residents.",
        "Review cover for that day. Compliance is assessed quarterly against census.",
        OWN.ADMINISTRATOR,
        params_from_pack=("hprd_minimums",),
    ),
]


def build_registry() -> RuleRegistry:
    """The catalog, assembled. One registry per process is plenty."""
    registry = RuleRegistry()
    registry.register_all(
        [
            *FILE_RULES,
            *FORMAT_RULES,
            *IDENTITY_RULES,
            *CROSS_SOURCE_RULES,
            *TIME_RULES,
            *PDF_RULES,
            *DOMAIN_RULES,
        ]
    )
    return registry


RULES = build_registry()
