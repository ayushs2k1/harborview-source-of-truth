"""The four-way match and the staffing view."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from sot.ledger.authority import Authority
from sot.ledger.claims import Claim
from sot.ledger.golden import Credential, PayLine, survive
from sot.match.fourway import (
    STATUS_HOURS_VARIANCE,
    STATUS_MATCHED,
    STATUS_NOT_EMPLOYED,
    STATUS_NOT_PERMITTED,
    STATUS_PAID_NOT_SCHEDULED,
    STATUS_SCHEDULED_NOT_PAID,
    STATUS_UNKNOWN,
    Coverage,
    Period,
    build_coverage,
    build_periods,
    run_match,
    week_containing,
)
from sot.tri import Tri
from sot.views.staffing import TIER_CONFLICT, TIER_SCHEDULE_ONLY, TIER_VERIFIED, build_daily_hours

WEEK = Period(date(2026, 9, 14), date(2026, 9, 20))


class FakePerson:
    def __init__(self, person_id="P-1", display_name="Ann Abernathy", role="RN", facility="BYS"):
        self.person_id = person_id
        self.display_name = display_name
        self.role_code = role
        self.facility_code = facility


def golden_with(**attributes):
    claims = [
        Claim("person", "P-1", attribute, value, "hr", "roster")
        for attribute, value in attributes.items()
    ]
    return survive(claims, Authority())


def segment(day: int, hours=8.0, category="WORK", facility="BYS", role="RN", **kwargs):
    work_date = date(2026, 9, day)
    start = kwargs.pop("start", datetime(2026, 9, day, 7, 0))
    end = kwargs.pop("end", datetime(2026, 9, day, 15, 0))
    return {
        "segment_id": kwargs.pop("segment_id", f"S-{day}-{facility}-{category}"),
        "person_id": kwargs.pop("person_id", "P-1"),
        "facility_code": facility,
        "role_code": role,
        "work_date": work_date,
        "start_ts": start,
        "end_ts": end,
        "hours": hours,
        "category": category,
        "source_type": "schedule",
        "page": 1,
        "row_index": 2,
        **kwargs,
    }


def pay(hours=40.0, facility="BYS", role="RN", start=date(2026, 9, 14), end=date(2026, 9, 20)):
    return PayLine(
        pay_line_id=f"PL-{facility}-{start}",
        person_id="P-1",
        facility_code=facility,
        role_code=role,
        period_start=start,
        period_end=end,
        hours_paid=hours,
    )


def match(segments=(), pay_lines=(), credentials=(), golden=None, **kwargs):
    return run_match(
        persons=[FakePerson()],
        pay_lines=list(pay_lines),
        segments=list(segments),
        credentials=list(credentials),
        golden=golden if golden is not None else golden_with(hire_date="2020-01-01"),
        # No role requires a credential unless a test says so, so the arithmetic
        # tests isolate the arithmetic rather than tripping the permission check.
        required_credential=kwargs.pop("required_credential", {}),
        tolerance=kwargs.pop("tolerance", 0.25),
        **kwargs,
    )


# --- periods and coverage ---------------------------------------------------


def test_the_pack_week_is_used_for_rota_dates_payroll_has_not_reached():
    assert week_containing(date(2026, 9, 17)) == WEEK


def test_payroll_periods_are_used_where_payroll_has_them():
    periods = build_periods([pay()], [segment(17)])
    assert periods == [WEEK]


def test_rota_dates_outside_every_pay_period_get_their_own_week():
    periods = build_periods([pay()], [segment(28)])
    assert len(periods) == 2


def test_coverage_comes_from_the_data():
    coverage = build_coverage([pay()], [segment(14), segment(16)])
    assert coverage.schedule == Period(date(2026, 9, 14), date(2026, 9, 16))
    assert coverage.payroll == WEEK
    assert coverage.both == Period(date(2026, 9, 14), date(2026, 9, 16))


def test_sources_that_do_not_overlap_have_no_common_coverage():
    coverage = Coverage(
        schedule=Period(date(2026, 9, 1), date(2026, 9, 7)),
        payroll=Period(date(2026, 9, 14), date(2026, 9, 20)),
    )
    assert coverage.both is None
    assert not coverage.comparable(WEEK)


def test_one_source_alone_has_no_common_coverage():
    assert Coverage(schedule=Period(date(2026, 9, 1), date(2026, 9, 7))).both is None


# --- week statuses ----------------------------------------------------------


def test_a_week_that_reconciles_is_matched():
    result = match([segment(day) for day in (14, 15, 16, 17, 18)], [pay(40.0)])
    assert result.weeks[0].status == STATUS_MATCHED


def test_a_small_difference_is_within_tolerance():
    result = match([segment(14, hours=7.9)], [pay(8.0)])
    assert result.weeks[0].status == STATUS_MATCHED


def test_a_real_difference_is_a_variance_with_a_direction():
    result = match([segment(14)], [pay(12.0)])
    week = result.weeks[0]
    assert week.status == STATUS_HOURS_VARIANCE
    assert week.direction == "PAID_MORE"
    assert week.delta == 4.0


def test_paid_less_than_scheduled_points_the_other_way():
    result = match([segment(14), segment(15)], [pay(8.0)])
    assert result.weeks[0].direction == "PAID_LESS"


def test_paid_leave_explains_a_difference():
    """The week reconciles once the leave is counted, so this is explained rather
    than wrong - and the flag drops to informational because of it."""
    segments = [segment(day) for day in (14, 15, 16, 18)] + [
        segment(17, category="PTO", segment_id="S-pto")
    ]
    result = match(segments, [pay(40.0)])
    week = result.weeks[0]
    assert week.status == STATUS_HOURS_VARIANCE
    assert week.explained_by_pto
    assert week.scheduled_pto_hours == 8.0


def test_leave_that_does_not_account_for_the_difference_is_not_an_explanation():
    segments = [segment(14), segment(15, category="PTO", segment_id="S-pto")]
    result = match(segments, [pay(30.0)])
    assert not result.weeks[0].explained_by_pto


def test_paid_with_nothing_on_the_rota():
    result = match([segment(14, facility="RVD")], [pay(40.0, facility="BYS")])
    bys = next(week for week in result.weeks if week.facility_code == "BYS")
    assert bys.status == STATUS_PAID_NOT_SCHEDULED


def test_on_the_rota_with_no_pay():
    result = match([segment(14, facility="RVD")], [pay(40.0, facility="BYS")])
    rvd = next(week for week in result.weeks if week.facility_code == "RVD")
    assert rvd.status == STATUS_SCHEDULED_NOT_PAID


def test_working_before_being_hired_outranks_the_arithmetic():
    """A week that reconciles perfectly is still a problem if the person should not
    have been there."""
    result = match([segment(14)], [pay(8.0)], golden=golden_with(hire_date="2027-01-01"))
    assert result.weeks[0].status == STATUS_NOT_EMPLOYED


def test_working_without_a_credential_outranks_the_arithmetic():
    result = match([segment(14)], [pay(8.0)], required_credential={"RN": ["RN"]})
    assert result.weeks[0].status == STATUS_NOT_PERMITTED


def test_a_valid_credential_permits_the_week():
    credential = Credential(
        credential_id="CR-1",
        holder_id="P-1",
        credential_type="RN",
        expires_on=date(2027, 1, 1),
    )
    result = match(
        [segment(14)],
        [pay(8.0)],
        credentials=[credential],
        required_credential={"RN": ["RN"]},
    )
    assert result.weeks[0].permitted is Tri.PASS
    assert result.weeks[0].status == STATUS_MATCHED


def test_a_role_needing_nothing_is_permitted():
    result = match(
        [segment(14, role="CLERK")],
        [pay(8.0, role="CLERK")],
        required_credential={"RN": ["RN"]},
    )
    assert result.weeks[0].status == STATUS_MATCHED


def test_no_hire_date_makes_employment_unknown_not_false():
    """ "We have no record of when they started" is not "they did not work here"."""
    result = match([segment(14)], [pay(8.0)], golden=golden_with(phone="x"))
    assert result.weeks[0].employed is Tri.UNKNOWN
    assert result.weeks[0].status != STATUS_NOT_EMPLOYED


def test_a_week_outside_the_common_coverage_is_not_judged():
    """Payroll three weeks longer than the rota is weeks nobody sent a rota for, not
    everybody failing to turn up."""
    result = match([segment(14)], [pay(40.0, start=date(2026, 9, 21), end=date(2026, 9, 27))])
    later = next(week for week in result.weeks if week.period.start == date(2026, 9, 21))
    assert later.in_both_coverages is False
    assert later.status == STATUS_UNKNOWN


def test_a_termination_before_the_period_ends_employment():
    result = match(
        [segment(14)],
        [pay(8.0)],
        golden=golden_with(hire_date="2020-01-01", termination_date="2026-01-01"),
    )
    assert result.weeks[0].employed is Tri.FAIL


# --- person-days ------------------------------------------------------------


def test_a_day_knows_whether_a_credential_covered_it():
    expired = Credential(
        credential_id="CR-1",
        holder_id="P-1",
        credential_type="RN",
        expires_on=date(2026, 9, 15),
    )
    result = match(
        [segment(14), segment(16)],
        credentials=[expired],
        required_credential={"RN": ["RN"]},
    )
    by_date = {day.work_date: day.credential_valid for day in result.days}
    assert by_date[date(2026, 9, 14)] is Tri.PASS
    assert by_date[date(2026, 9, 16)] is Tri.FAIL


def test_being_in_two_places_at_once_is_detected_across_sites():
    overlapping = [
        segment(14, facility="BYS", segment_id="S-a"),
        segment(
            14,
            facility="RVD",
            segment_id="S-b",
            start=datetime(2026, 9, 14, 14, 0),
            end=datetime(2026, 9, 14, 22, 0),
        ),
    ]
    result = match(overlapping)
    assert any(day.has_overlap for day in result.days)


def test_back_to_back_shifts_do_not_overlap():
    adjacent = [
        segment(14, segment_id="S-a"),
        segment(
            14,
            segment_id="S-b",
            start=datetime(2026, 9, 14, 15, 0),
            end=datetime(2026, 9, 14, 23, 0),
        ),
    ]
    assert not any(day.has_overlap for day in match(adjacent).days)


# --- the staffing view ------------------------------------------------------


class FakePack:
    def __init__(self, **settings):
        self._settings = {
            "pbj.split_at_midnight": True,
            "pbj.include_training": False,
            "pbj.meal_deduction": {"minutes": 30, "min_shift_hours": 6},
            "payroll_attribution": "shift_start",
            **settings,
        }

    def setting(self, dotted, default=None):
        return self._settings.get(dotted, default)


def staffing(segments, pay_lines=(), **pack_settings):
    result = match(segments, pay_lines)
    return build_daily_hours(
        segments=list(segments),
        match=result,
        pack=FakePack(**pack_settings),
        display_names={"P-1": "Ann Abernathy"},
        pbj_codes={"RN": "7"},
    )


def test_an_overnight_shift_is_reported_on_both_days():
    """Reported staffing is counted by calendar day, which is not how a rota is
    written."""
    night = segment(
        19,
        hours=8.0,
        start=datetime(2026, 9, 19, 23, 0),
        end=datetime(2026, 9, 20, 7, 0),
        segment_id="S-night",
    )
    rows = staffing([night]).rows
    assert [row.work_date for row in rows] == [date(2026, 9, 19), date(2026, 9, 20)]
    assert sum(row.scheduled_hours for row in rows) == pytest.approx(8.0)


def test_the_meal_break_is_deducted_once_per_shift():
    rows = staffing([segment(14)]).rows
    assert rows[0].scheduled_hours == 8.0
    assert rows[0].meal_deduction == 0.5
    assert rows[0].pbj_hours == 7.5


def test_a_short_shift_keeps_its_whole_length():
    rows = staffing([segment(14, hours=4.0, end=datetime(2026, 9, 14, 11, 0))]).rows
    assert rows[0].meal_deduction == 0.0


def test_the_break_is_deducted_on_the_day_the_shift_began():
    """Where it was actually taken is unknowable from a rota, and splitting it would
    imply a precision the source does not have."""
    night = segment(
        19,
        hours=8.0,
        start=datetime(2026, 9, 19, 23, 0),
        end=datetime(2026, 9, 20, 7, 0),
        segment_id="S-night",
    )
    rows = staffing([night]).rows
    assert rows[0].meal_deduction == 0.5
    assert rows[1].meal_deduction == 0.0


def test_training_is_excluded_from_reported_hours_by_default():
    rows = staffing([segment(14, category="TRAINING")]).rows
    assert rows == []


def test_a_pack_can_count_training():
    rows = staffing([segment(14, category="TRAINING")], **{"pbj.include_training": True}).rows
    assert len(rows) == 1


def test_leave_is_never_reported_as_staffing():
    assert staffing([segment(14, category="PTO")]).rows == []


def test_hours_whose_week_reconciles_are_verified():
    rows = staffing([segment(14)], [pay(8.0)]).rows
    assert rows[0].tier == TIER_VERIFIED


def test_hours_whose_week_does_not_reconcile_are_shown_and_marked():
    rows = staffing([segment(14)], [pay(20.0)]).rows
    assert rows[0].tier == TIER_CONFLICT


def test_hours_with_no_payroll_are_marked_as_such():
    rows = staffing([segment(14)]).rows
    assert rows[0].tier == TIER_SCHEDULE_ONLY


def test_paid_hours_with_no_rota_day_are_never_given_one():
    """Inventing a date to make a total balance is what an audit looks for."""
    result = staffing([segment(14, facility="RVD")], [pay(40.0, facility="BYS")])
    assert all(row.facility_code == "RVD" for row in result.rows)
    assert [item.hours for item in result.unallocated] == [40.0]


def test_the_assumptions_are_recorded_beside_the_numbers():
    result = staffing([segment(14)])
    assert result.assumptions["meal_deduction_minutes"] == 30
    assert result.assumptions["split_at_midnight"] is True
