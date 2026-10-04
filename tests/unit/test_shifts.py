"""The shift grammar.

The spec asks for at least forty of these, and it is right to: every form below is one
a printed rota actually uses, and the hours that come out of this parser are the hours
that get reported to the regulator.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from sot.normalize.shifts import (
    ShiftCategory,
    build_codes,
    clock_hours,
    normalize_dashes,
    parse_footnote,
    parse_shift_cell,
    split_at_midnight,
)

FOOTNOTE_TEXT = "Shifts: 7a-3p, 3p-11p, 11p-7a are 8 hours. 7a-7p is 12 hours."


@pytest.fixture(scope="module")
def footnote():
    return parse_footnote(FOOTNOTE_TEXT)


def parse(cell: str, footnote=None):
    return parse_shift_cell(cell, footnote=footnote)


def segments(cell: str, footnote=None):
    result = parse(cell, footnote)
    assert result.value is not None, f"{cell!r} did not parse: {result.note}"
    return result.value.segments


def one(cell: str, footnote=None):
    found = segments(cell, footnote)
    assert len(found) == 1, f"{cell!r} gave {len(found)} segments"
    return found[0]


# --- the written forms ------------------------------------------------------


@pytest.mark.parametrize(
    "cell",
    [
        "7a-3p",
        "7A-3P",
        "7am-3pm",
        "7AM-3PM",
        "7 a - 3 p",
        "7a.m.-3p.m.",
        "7:00a-3:00p",
        "7:00 AM - 3:00 PM",
        "0700-1500",
        "07:00-15:00",
        "7:00-15:00",
    ],
)
def test_a_day_shift_is_read_the_same_however_it_is_written(cell: str):
    segment = one(cell)
    assert (segment.start, segment.end) == (time(7, 0), time(15, 0))
    assert segment.clock_hours == 8.0


@pytest.mark.parametrize(
    ("cell", "start", "end"),
    [
        ("3p-11p", time(15, 0), time(23, 0)),
        ("11p-7a", time(23, 0), time(7, 0)),
        ("7p-7a", time(19, 0), time(7, 0)),
        ("7a-7p", time(7, 0), time(19, 0)),
        ("12a-8a", time(0, 0), time(8, 0)),
        ("12p-8p", time(12, 0), time(20, 0)),
        ("6:30a-2:30p", time(6, 30), time(14, 30)),
        ("2330-0730", time(23, 30), time(7, 30)),
    ],
)
def test_times_of_day_are_read_correctly(cell: str, start: time, end: time):
    segment = one(cell)
    assert (segment.start, segment.end) == (start, end)


@pytest.mark.parametrize(
    "dash",
    ["-", *(chr(code) for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212))],
)
def test_every_dash_a_printed_page_uses_is_accepted(dash: str):
    """M34: an en dash out of a word processor must read the same as a hyphen."""
    segment = one(f"7a{dash}3p")
    assert (segment.start, segment.end) == (time(7, 0), time(15, 0))


def test_normalize_dashes_collapses_repeats():
    assert normalize_dashes("7a--3p") == "7a-3p"


def test_surrounding_whitespace_is_ignored():
    assert one("  7a-3p  ").clock_hours == 8.0


# --- overnight --------------------------------------------------------------


def test_an_overnight_shift_is_marked_as_one():
    segment = one("11p-7a")
    assert segment.overnight is True
    assert segment.clock_hours == 8.0


def test_a_day_shift_is_not_overnight():
    assert one("7a-3p").overnight is False


def test_timestamps_roll_over_midnight():
    segment = one("11p-7a")
    start, end = segment.timestamps(date(2026, 9, 19))
    assert start == datetime(2026, 9, 19, 23, 0)
    assert end == datetime(2026, 9, 20, 7, 0)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (time(7, 0), time(15, 0), 8.0),
        (time(23, 0), time(7, 0), 8.0),
        (time(19, 0), time(7, 0), 12.0),
        (time(7, 0), time(7, 30), 0.5),
    ],
)
def test_clock_hours_handles_the_wrap(start: time, end: time, expected: float):
    assert clock_hours(start, end) == expected


def test_equal_start_and_end_reads_as_a_full_day_not_nothing():
    """Almost certainly a mistake in the source. Reporting 24 hours gets it caught by
    the daily cap; reporting zero would hide it."""
    assert clock_hours(time(7, 0), time(7, 0)) == 24.0


# --- the footnote -----------------------------------------------------------


def test_the_footnote_is_parsed_into_shift_lengths(footnote):
    assert footnote.hours_for(time(7, 0), time(15, 0)) == 8.0
    assert footnote.hours_for(time(23, 0), time(7, 0)) == 8.0
    assert footnote.hours_for(time(7, 0), time(19, 0)) == 12.0


def test_the_footnote_is_authoritative_over_the_clock(footnote):
    """It is the facility telling us what its shifts are worth, breaks included."""
    hand_written = parse_footnote("7a-3p is 7.5 hours.")
    segment = one("7a-3p", hand_written)
    assert segment.hours == 7.5
    assert segment.clock_hours == 8.0
    assert segment.hours_source == "footnote"


def test_a_shift_the_footnote_does_not_define_falls_back_to_the_clock(footnote):
    """M35: 7p-7a is not in the footnote, so twelve hours is computed."""
    segment = one("7p-7a", footnote)
    assert segment.hours == 12.0
    assert segment.hours_source == "clock"


def test_without_a_footnote_everything_comes_from_the_clock():
    """M39: no shift-length note on the page."""
    segment = one("7a-3p", None)
    assert segment.hours == 8.0
    assert segment.hours_source == "clock"


def test_the_footnote_pattern_is_generic_not_a_fixed_sentence():
    """Every facility writes this note differently and none will rewrite it for us."""
    table = parse_footnote("Day 7a-3p and evening 3p-11p are 8 hrs; 7a-7p is 12 hours")
    assert table.hours_for(time(7, 0), time(15, 0)) == 8.0
    assert table.hours_for(time(15, 0), time(23, 0)) == 8.0
    assert table.hours_for(time(7, 0), time(19, 0)) == 12.0


def test_a_footnote_with_decimal_hours_is_read():
    assert parse_footnote("7a-3p is 7.5 hours.").hours_for(time(7, 0), time(15, 0)) == 7.5


def test_an_absent_footnote_is_falsy():
    assert not parse_footnote("")
    assert not parse_footnote("Please see the nurse manager with any questions.")


# --- ambiguity --------------------------------------------------------------


def test_a_bare_range_is_resolved_from_the_footnote(footnote):
    result = parse("7-3", footnote)
    assert result.code == "SHIFT_AMBIGUOUS_ASSUMED"
    assert (result.value.segments[0].start, result.value.segments[0].end) == (
        time(7, 0),
        time(15, 0),
    )


def test_a_bare_range_without_a_footnote_reads_as_a_day_shift():
    result = parse("7-3", None)
    assert result.code == "SHIFT_AMBIGUOUS_ASSUMED"
    assert result.value.segments[0].end == time(15, 0)


def test_a_bare_range_reads_as_a_day_shift_whenever_that_is_plausible():
    """3-1 really can be 3am to 1pm, so it is read, not refused."""
    assert one("3-1", None).clock_hours == 10.0


def test_a_bare_range_whose_only_reading_is_implausible_is_refused():
    """Midnight to 11 would have to be read as a 23-hour shift, so it is refused and
    flagged rather than invented."""
    assert parse("0-11", None).value is None


def test_an_explicit_time_is_never_treated_as_ambiguous(footnote):
    assert parse("7a-3p", footnote).code is None


def test_a_24_hour_clock_reading_is_not_ambiguous():
    assert parse("07:00-15:00", None).code is None


# --- doubles ----------------------------------------------------------------


@pytest.mark.parametrize(
    "cell", ["7a-3p/3p-11p", "7a-3p, 3p-11p", "7a-3p & 3p-11p", "7a-3p + 3p-11p"]
)
def test_a_double_shift_gives_two_segments(cell: str, footnote):
    found = segments(cell, footnote)
    assert len(found) == 2
    assert sum(segment.hours for segment in found) == 16.0


def test_a_single_long_shift_is_one_segment_not_two(footnote):
    assert len(segments("7a-11p", footnote)) == 1
    assert one("7a-11p", footnote).clock_hours == 16.0


# --- codes that are not shifts ----------------------------------------------


@pytest.mark.parametrize("cell", ["OFF", "Off", "off", "O", "X", "-", "--", "", "   ", "RDO"])
def test_a_day_off_produces_no_hours(cell: str):
    result = parse(cell)
    assert result.value.category is ShiftCategory.OFF
    assert result.value.total_hours == 0.0


@pytest.mark.parametrize(
    "cell", ["PTO", "VAC", "VACATION", "SICK", "SL", "HOL", "LOA", "FMLA", "BRV"]
)
def test_paid_leave_is_recognised(cell: str):
    assert parse(cell).value.category is ShiftCategory.PTO


@pytest.mark.parametrize("cell", ["ORIENT", "ORIENTATION", "TRN", "TRAINING", "INSERVICE"])
def test_training_is_recognised(cell: str):
    assert parse(cell).value.category is ShiftCategory.TRAINING


@pytest.mark.parametrize("cell", ["OC", "ON CALL", "ONCALL"])
def test_on_call_is_recognised(cell: str):
    assert parse(cell).value.category is ShiftCategory.ONCALL


def test_training_counts_as_worked_but_leave_does_not():
    assert ShiftCategory.TRAINING.is_worked
    assert ShiftCategory.WORK.is_worked
    assert not ShiftCategory.PTO.is_worked
    assert not ShiftCategory.ONCALL.is_worked
    assert not ShiftCategory.OFF.is_worked


def test_a_pack_can_add_its_own_codes():
    codes = build_codes({"pto": ["URLOP"]})
    assert parse_shift_cell("URLOP", codes=codes).value.category is ShiftCategory.PTO


def test_an_unrecognised_cell_is_flagged_rather_than_ignored():
    """M36. Silently dropping it would quietly remove somebody from the rota."""
    result = parse("lunch cover")
    assert result.value is None
    assert result.code == "SHIFT_UNPARSEABLE"


@pytest.mark.parametrize("cell", ["25a-3p", "7a-99p", "???", "see note"])
def test_nonsense_does_not_parse(cell: str):
    assert parse(cell).value is None


# --- hand-written annotations -----------------------------------------------


@pytest.mark.parametrize(
    ("cell", "marker"),
    [("7a-3p*", "*"), ("7a-3p (C)", "(C)"), ("7a-3p CN", "CN"), ("7a-3p #", "#")],
)
def test_an_annotation_is_kept_as_a_note_not_treated_as_part_of_the_shift(cell: str, marker: str):
    result = parse(cell)
    assert result.value.total_hours == 8.0
    assert marker in " ".join(result.value.markers)


def test_several_annotations_are_all_kept():
    result = parse("7a-3p (C)*")
    assert len(result.value.markers) == 2


# --- the midnight split -----------------------------------------------------


def test_an_overnight_shift_is_split_across_two_days():
    """M38. Reported staffing is counted by calendar day."""
    parts = split_at_midnight(datetime(2026, 9, 19, 23, 0), datetime(2026, 9, 20, 7, 0))
    assert parts == [(date(2026, 9, 19), 1.0), (date(2026, 9, 20), 7.0)]


def test_a_day_shift_stays_on_one_day():
    parts = split_at_midnight(datetime(2026, 9, 19, 7, 0), datetime(2026, 9, 19, 15, 0))
    assert parts == [(date(2026, 9, 19), 8.0)]


def test_a_footnote_length_is_shared_out_in_proportion():
    """The parts still have to add up to what the facility says the shift is worth."""
    parts = split_at_midnight(datetime(2026, 9, 19, 23, 0), datetime(2026, 9, 20, 7, 0), hours=7.5)
    assert sum(hours for _, hours in parts) == pytest.approx(7.5)
    assert parts[0][1] < parts[1][1]


def test_a_shift_spanning_three_days_is_split_three_ways():
    parts = split_at_midnight(datetime(2026, 9, 19, 23, 0), datetime(2026, 9, 21, 1, 0))
    assert [day for day, _ in parts] == [date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 21)]
    assert sum(hours for _, hours in parts) == 26.0


def test_an_empty_span_splits_into_nothing():
    assert split_at_midnight(datetime(2026, 9, 19, 7, 0), datetime(2026, 9, 19, 7, 0)) == []


# --- totals -----------------------------------------------------------------


def test_the_cell_total_adds_its_segments(footnote):
    assert parse("7a-3p/3p-11p", footnote).value.total_hours == 16.0


def test_a_worked_cell_knows_it_was_worked(footnote):
    assert parse("7a-3p", footnote).value.is_worked
    assert not parse("OFF", footnote).value.is_worked


def test_none_is_treated_as_a_day_off_not_an_error():
    assert parse_shift_cell(None).value.category is ShiftCategory.OFF
