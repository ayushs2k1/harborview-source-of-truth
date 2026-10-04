"""Names, nicknames, dates, phones, credential numbers, hours, and codes."""

from __future__ import annotations

from datetime import date

import pytest

from sot.normalize.codes import resolve_code
from sot.normalize.dates import ORDER_DMY, ORDER_MDY, infer_order, is_month_end, parse_date
from sot.normalize.hours import parse_hours
from sot.normalize.ids_licenses import parse_credential_number
from sot.normalize.names import fold, name_key, parse_name, titlecase
from sot.normalize.nicknames import are_variants, group_count, share_initial, variants_of
from sot.normalize.phones import parse_phone
from sot.normalize.result import Quality

# --- names ------------------------------------------------------------------


@pytest.mark.parametrize(
    "written",
    [
        "Sofia Reyes",
        "REYES, SOFIA",
        "reyes, sofia",
        "Reyes, Sofia",
        "Sofia Reyes, RN",
        "  SOFIA   REYES  ",
        "Reyes,Sofia",
    ],
)
def test_one_person_written_seven_ways_gives_one_key(written: str):
    """The four systems each write names differently. All of them have to agree."""
    assert name_key(written) == "reyes sofia"


def test_a_middle_name_does_not_change_the_key():
    assert name_key("Reyes, Sofia M.") == name_key("Sofia Reyes")


@pytest.mark.parametrize(
    ("written", "given", "family"),
    [
        ("Kevin O'Brien", "Kevin", "O'Brien"),
        ("O'BRIEN, KEVIN", "Kevin", "O'Brien"),
        ("Ana García-López", "Ana", "García-López"),
        ("GARCÍA-LÓPEZ, ANA", "Ana", "García-López"),
        ("José Peña", "José", "Peña"),
        ("Maria de la Cruz", "Maria", "de la Cruz"),
        ("van der Berg, Johan", "Johan", "van der Berg"),
        ("McDonald, Angus", "Angus", "McDonald"),
    ],
)
def test_awkward_names_survive_the_round_trip(written: str, given: str, family: str):
    parsed = parse_name(written).value
    assert (parsed.given, parsed.family) == (given, family)


def test_accents_are_folded_for_comparison_but_kept_for_display():
    """Peña and Pena are the same person; only one of them is their name."""
    assert name_key("José Peña") == name_key("Jose Pena")
    assert parse_name("PEÑA, JOSÉ").value.display == "José Peña"


@pytest.mark.parametrize(
    ("written", "suffix"),
    [("Robert Hayes Jr.", "Jr"), ("HAYES JR., ROBERT", "JR"), ("John Smith III", "III")],
)
def test_a_generational_suffix_is_separated_from_the_family_name(written: str, suffix: str):
    parsed = parse_name(written).value
    assert parsed.suffix.upper().rstrip(".") == suffix.upper().rstrip(".")
    assert "jr" not in parsed.family_key


def test_trailing_credentials_are_removed():
    parsed = parse_name("Jane Doe, RN, BSN")
    assert parsed.value.family == "Doe"
    assert parsed.value.credentials == ("RN", "BSN")
    assert parsed.quality is Quality.REPAIRED


def test_a_two_word_value_gives_up_a_clinical_licence_but_not_a_surname():
    """ "DOE RN" is a name and a credential. "ANN MA" is two names."""
    assert parse_name("DOE RN").value.family == "Doe"
    assert parse_name("ANN MA").value.family == "Ma"


def test_a_single_word_name_is_flagged_as_ambiguous():
    result = parse_name("Cher")
    assert result.quality is Quality.AMBIGUOUS
    assert result.value.family == "Cher"


def test_a_value_with_no_letters_is_not_a_name():
    assert parse_name("42").value is None


def test_an_empty_name_is_empty_rather_than_invalid():
    assert parse_name("").is_empty


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("REYES", "Reyes"),
        ("o'brien", "O'Brien"),
        ("GARCÍA-LÓPEZ", "García-López"),
        ("mcdonald", "McDonald"),
    ],
)
def test_shouted_and_whispered_names_are_recased(raw: str, expected: str):
    assert titlecase(raw) == expected


def test_a_name_already_in_mixed_case_is_left_alone():
    """The source already knows that van der Berg is not Van Der Berg."""
    assert titlecase("van der Berg") == "van der Berg"


def test_fold_removes_punctuation_and_case():
    assert fold("O'Brien-Smith") == "obriensmith"


# --- nicknames --------------------------------------------------------------


def test_the_table_is_substantial():
    assert group_count() > 400


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Marc", "Marcus"),
        ("Marc", "Mark"),
        ("Kate", "Katherine"),
        ("Katie", "Catherine"),
        ("Sofia", "Sophia"),
        ("Steven", "Stephen"),
        ("Bill", "William"),
        ("Bob", "Robert"),
        ("Liz", "Elizabeth"),
        ("Beth", "Elizabeth"),
        ("Jose", "Pepe"),
        ("Francisco", "Paco"),
    ],
)
def test_known_variants_are_recognised(first: str, second: str):
    assert are_variants(first, second)
    assert are_variants(second, first), "the relation has to be symmetric"


def test_unrelated_names_are_not_variants():
    assert not are_variants("Marcus", "Sofia")
    assert not are_variants("Robert", "Richard")


def test_accents_do_not_break_the_lookup():
    assert are_variants("José", "Jose")


def test_a_name_is_a_variant_of_itself():
    assert are_variants("Priya", "Priya")


def test_an_unknown_name_has_only_itself():
    assert variants_of("Zzyzx") == frozenset({"zzyzx"})


def test_an_empty_name_matches_nothing():
    assert not are_variants("", "Marc")


def test_a_shared_initial_is_recognised_separately():
    """Weak evidence, scored far below a known variant - but it is what links M. Bell."""
    assert share_initial("M", "Marcus")
    assert not share_initial("K", "Marcus")


# --- dates ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-09-14", date(2026, 9, 14)),
        ("2026/09/14", date(2026, 9, 14)),
        ("9/14/2026", date(2026, 9, 14)),
        ("09-14-2026", date(2026, 9, 14)),
        ("9/14/26", date(2026, 9, 14)),
        ("14-Sep-2026", date(2026, 9, 14)),
        ("September 14, 2026", date(2026, 9, 14)),
        ("Sep 14 2026", date(2026, 9, 14)),
        ("20260914", date(2026, 9, 14)),
    ],
)
def test_the_usual_date_formats_are_read(raw: str, expected: date):
    assert parse_date(raw).value == expected


def test_a_spreadsheet_serial_is_converted():
    """M10: a date column exported as numbers."""
    result = parse_date("45914")
    assert result.value == date(2025, 9, 14)
    assert result.code == "EXCEL_SERIAL_DATE"


def test_a_number_outside_the_plausible_range_is_not_a_date():
    """An identifier in a date column is not 1908."""
    assert parse_date("1234").value is None


@pytest.mark.parametrize(
    ("raw", "expected"), [("9/14/69", date(2069, 9, 14)), ("9/14/70", date(1970, 9, 14))]
)
def test_two_digit_years_pivot_at_seventy(raw: str, expected: date):
    assert parse_date(raw).value == expected


def test_an_unambiguous_date_needs_no_assumption():
    """14 cannot be a month, so no guess is involved whichever order the column uses."""
    assert parse_date("14/9/2026", order=ORDER_MDY).value == date(2026, 9, 14)


def test_an_ambiguous_date_follows_the_given_order_and_says_so():
    """M11."""
    result = parse_date("3/4/2026", order=ORDER_MDY)
    assert result.value == date(2026, 3, 4)
    assert result.code == "DATE_AMBIGUOUS_ASSUMED"
    assert parse_date("3/4/2026", order=ORDER_DMY).value == date(2026, 4, 3)


def test_a_column_settles_its_own_order():
    """One date with a day above twelve is evidence, and beats any default."""
    assert infer_order(["3/4/2026", "14/9/2026"])[0] == ORDER_DMY
    assert infer_order(["3/4/2026", "9/14/2026"])[0] == ORDER_MDY


def test_a_column_with_both_orders_settles_nothing():
    order, basis = infer_order(["14/9/2026", "9/14/2026"])
    assert order is None
    assert "both orders" in basis


def test_a_column_of_ambiguous_dates_settles_nothing():
    assert infer_order(["3/4/2026", "5/6/2026"])[0] is None


def test_an_impossible_date_is_refused():
    """M12."""
    result = parse_date("2026-02-30")
    assert result.value is None
    assert result.code == "DATE_IMPOSSIBLE"


def test_free_text_is_refused():
    """M57."""
    result = parse_date("spring 2020")
    assert result.value is None
    assert result.code == "DATE_UNPARSEABLE"


def test_a_date_object_passes_straight_through():
    assert parse_date(date(2026, 9, 14)).value == date(2026, 9, 14)


def test_month_end_detection():
    assert is_month_end(date(2026, 12, 31))
    assert is_month_end(date(2028, 2, 29)), "leap year"
    assert not is_month_end(date(2026, 12, 15))


# --- phones -----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "718-555-0201",
        "(718) 555-0201",
        "7185550201",
        "718.555.0201",
        "1-718-555-0201",
        "+1 (718) 555-0201",
        "  718 555 0201  ",
    ],
)
def test_a_phone_number_reduces_to_ten_digits(raw: str):
    """M13."""
    assert parse_phone(raw).value.digits == "7185550201"


def test_the_display_form_is_consistent():
    assert parse_phone("7185550201").value.display == "(718) 555-0201"


def test_an_extension_is_kept_separately():
    parsed = parse_phone("718-555-0201 x42").value
    assert (parsed.digits, parsed.extension) == ("7185550201", "42")
    assert parsed.key == "7185550201", "a shared switchboard is not a shared phone"


@pytest.mark.parametrize(
    "raw", ["555-0201", "018-555-0201", "718-155-0201", "not a phone", "12345"]
)
def test_an_unusable_number_is_flagged(raw: str):
    result = parse_phone(raw)
    assert result.value is None
    assert result.code == "PHONE_INVALID"


def test_a_test_number_is_perfectly_valid():
    """555 numbers are reserved for examples and appear throughout real test data."""
    assert parse_phone("718-555-0201").value is not None


# --- credential numbers -----------------------------------------------------

PREFIXES = {"RN": ("RN",), "LPN": ("LPN", "LVN"), "CNA": ("CNA", "NA")}


@pytest.mark.parametrize("raw", ["RN-551203", "rn551203", "RN 551203", "RN_551203", "551203"])
def test_a_credential_number_matches_however_it_is_written(raw: str):
    """M14: the strongest link in the system has to survive being retyped."""
    parsed = parse_credential_number(raw, credential_type="RN", prefixes_by_type=PREFIXES)
    assert parsed.value.key == "RN:551203"


def test_a_missing_prefix_is_inferred_from_the_type():
    parsed = parse_credential_number("551203", credential_type="RN", prefixes_by_type=PREFIXES)
    assert parsed.value.normalized == "RN-551203"


def test_look_alike_characters_are_read_as_digits():
    parsed = parse_credential_number("CNA-77IO45", credential_type="CNA", prefixes_by_type=PREFIXES)
    assert parsed.value.digits == "771045"
    assert parsed.code == "LICENSE_NUMBER_CHAR_CONFUSION"


def test_a_prefix_that_contradicts_its_type_is_flagged_but_the_number_is_kept():
    """M15. Which of the two is wrong changes who may work, so neither is discarded."""
    parsed = parse_credential_number("CNA-551203", credential_type="RN", prefixes_by_type=PREFIXES)
    assert parsed.code == "LICENSE_PREFIX_TYPE_MISMATCH"
    assert parsed.value.digits == "551203"


def test_the_type_is_inferred_from_the_prefix_when_not_given():
    parsed = parse_credential_number("LPN-330912", prefixes_by_type=PREFIXES)
    assert parsed.value.credential_type == "LPN"


def test_a_value_with_no_digits_is_not_a_credential_number():
    assert parse_credential_number("abc", prefixes_by_type=PREFIXES).value is None


def test_different_types_sharing_digits_do_not_collide():
    rn = parse_credential_number("RN-1234", credential_type="RN", prefixes_by_type=PREFIXES)
    cna = parse_credential_number("CNA-1234", credential_type="CNA", prefixes_by_type=PREFIXES)
    assert rn.value.key != cna.value.key


# --- hours ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("36", 36.0),
        ("36.5", 36.5),
        ("36,5", 36.5),
        ("36:30", 36.5),
        ("36h 30m", 36.5),
        ("40 hrs", 40.0),
        ("40 hours", 40.0),
        ("40h", 40.0),
        (" 8 ", 8.0),
        (36, 36.0),
        (36.5, 36.5),
    ],
)
def test_hours_are_read_in_every_form_an_export_produces(raw, expected: float):
    """M16."""
    assert parse_hours(raw).value == expected


def test_a_thousands_separator_is_not_a_decimal_comma():
    assert parse_hours("1,234").value == 1234.0


def test_negative_hours_are_kept_and_flagged():
    """Usually a correction to an earlier period. Dropping it would leave the earlier
    overpayment uncorrected."""
    result = parse_hours("-4")
    assert result.value == -4.0
    assert result.code == "HOURS_NEGATIVE"


def test_words_are_not_hours():
    """M59."""
    result = parse_hours("forty")
    assert result.value is None
    assert result.code == "HOURS_UNPARSEABLE"


def test_an_empty_value_is_empty_rather_than_zero():
    """Zero hours and no record of hours are different statements."""
    assert parse_hours("").is_empty


# --- codes ------------------------------------------------------------------


def test_a_facility_is_resolved_through_the_crosswalk(pack):
    crosswalk = pack.crosswalk("facilities")
    codes = {resolve_code(raw, crosswalk).value for raw in ("Harborview Bayside", "BYS", "bayside")}
    assert len(codes) == 1


def test_a_role_title_is_resolved_to_a_canonical_code(pack):
    crosswalk = pack.crosswalk("roles")
    assert resolve_code("Registered Nurse", crosswalk).value == "RN"
    assert resolve_code("Certified Nurse Aide", crosswalk).value == "CNA"
    assert resolve_code("DON", crosswalk).value == "RN_DON"


def test_an_unknown_facility_code_is_flagged(pack):
    """M52."""
    result = resolve_code("HVB", pack.crosswalk("facilities"))
    assert result.value is None
    assert result.code == "CODE_UNKNOWN_FACILITY"


def test_an_unknown_job_code_is_flagged(pack):
    """M53."""
    result = resolve_code("FLT", pack.crosswalk("roles"))
    assert result.value is None
    assert result.code == "CODE_UNKNOWN_ROLE"


def test_a_title_that_does_not_identify_a_role_is_left_for_the_credential_to_settle(pack):
    """Guessing would put the hours in the wrong staffing category."""
    result = resolve_code(
        "Charge Nurse",
        pack.crosswalk("roles"),
        ambiguous_values=pack.setting("ambiguous_role_titles"),
    )
    assert result.value is None
    assert result.quality is Quality.AMBIGUOUS
    assert result.code is None, "not an error, just undecided"
