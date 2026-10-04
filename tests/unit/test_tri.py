"""Three-valued logic. Principle 6: unknown is never green."""

from __future__ import annotations

import pytest

from sot.tri import Tri, from_bool, tri_all, tri_any

PASS, FAIL, UNKNOWN = Tri.PASS, Tri.FAIL, Tri.UNKNOWN


def test_only_pass_is_green():
    assert PASS.is_green
    assert not FAIL.is_green
    assert not UNKNOWN.is_green


def test_unknown_is_not_known():
    assert PASS.is_known and FAIL.is_known
    assert not UNKNOWN.is_known


@pytest.mark.parametrize(("value", "expected"), [(PASS, FAIL), (FAIL, PASS), (UNKNOWN, UNKNOWN)])
def test_negation(value, expected):
    assert ~value is expected


@pytest.mark.parametrize(("value", "expected"), [(True, PASS), (False, FAIL), (None, UNKNOWN)])
def test_from_bool(value, expected):
    assert from_bool(value) is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([PASS, PASS], PASS),
        ([PASS, UNKNOWN], UNKNOWN),
        ([PASS, FAIL], FAIL),
        ([UNKNOWN, FAIL], FAIL),  # a known failure beats an unknown
        ([UNKNOWN, UNKNOWN], UNKNOWN),
    ],
)
def test_tri_all(values, expected):
    assert tri_all(values) is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([FAIL, FAIL], FAIL),
        ([FAIL, UNKNOWN], UNKNOWN),
        ([FAIL, PASS], PASS),
        ([UNKNOWN, PASS], PASS),  # a known success beats an unknown
        ([UNKNOWN, UNKNOWN], UNKNOWN),
    ],
)
def test_tri_any(values, expected):
    assert tri_any(values) is expected


def test_empty_is_unknown_not_vacuously_true():
    """'Every worked day was covered' must not pass when no days are on record.

    The usual cause of an empty series is a source that failed to load, and reporting
    that as compliant is exactly the failure mode principle 6 exists to prevent.
    """
    assert tri_all([]) is UNKNOWN
    assert tri_any([]) is UNKNOWN


def test_tri_serializes_as_its_name():
    """Stored in DuckDB as a string, so the wire form has to be the readable one."""
    assert Tri.UNKNOWN.value == "UNKNOWN"
    assert f"{Tri.PASS.value}" == "PASS"
