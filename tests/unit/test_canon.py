"""Canonical serialization, ordering, and rounding."""

from __future__ import annotations

import random
from datetime import date, datetime
from decimal import Decimal

import pytest

from sot.canon import (
    canonical_json,
    dedupe,
    nfkd_fold,
    round_hours,
    sort_records,
    squeeze,
    sum_hours,
)


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": 2, "c": {"z": 1, "y": 2}}
    b = {"c": {"y": 2, "z": 1}, "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_renders_dates_and_decimals():
    payload = {"d": date(2026, 9, 21), "t": datetime(2026, 9, 21, 7, 0), "n": Decimal("36.50")}
    assert canonical_json(payload) == '{"d":"2026-09-21","n":"36.50","t":"2026-09-21T07:00:00"}'


def test_canonical_json_sorts_sets():
    assert canonical_json({"s": {"b", "a"}}) == canonical_json({"s": {"a", "b"}})


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_canonical_json_rejects_unknown_types():
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


def test_sort_records_puts_nulls_last():
    rows = [{"k": "b"}, {"k": None}, {"k": "a"}]
    assert [r["k"] for r in sort_records(rows, "k")] == ["a", "b", None]


def test_sort_records_orders_numbers_numerically():
    rows = [{"n": 10}, {"n": 2}, {"n": -1}]
    assert [r["n"] for r in sort_records(rows, "n")] == [-1, 2, 10]


def test_sort_records_is_multi_key():
    rows = [
        {"f": "B", "n": "x"},
        {"f": "A", "n": "y"},
        {"f": "A", "n": "x"},
    ]
    assert [(r["f"], r["n"]) for r in sort_records(rows, "f", "n")] == [
        ("A", "x"),
        ("A", "y"),
        ("B", "x"),
    ]


def test_dedupe_preserves_first_seen_order():
    assert dedupe(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_dedupe_handles_unhashable_values():
    assert dedupe([{"a": 1}, {"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (8, 8.0), (7.999999999, 8.0), (36.5, 36.5), (float("inf"), None)],
)
def test_round_hours(value, expected):
    assert round_hours(value) == expected


def test_sum_hours_is_order_independent():
    """Float addition is not associative; the engine's totals must not care."""
    values = [0.1, 0.2, 0.3, 7.5, 12.0, 0.7]
    shuffled = values[:]
    random.Random(1).shuffle(shuffled)
    assert sum_hours(values) == sum_hours(shuffled)


def test_sum_hours_skips_nulls():
    assert sum_hours([8.0, None, 4.0]) == 12.0


def test_sum_hours_of_nothing_is_zero():
    assert sum_hours([]) == 0.0


def test_nfkd_fold_strips_accents():
    assert nfkd_fold("Peña") == "Pena"
    assert nfkd_fold("García-López") == "Garcia-Lopez"


def test_squeeze_collapses_whitespace():
    assert squeeze("  REYES,   SOFIA \t\n") == "REYES, SOFIA"


def test_sort_records_handles_mixed_types_without_raising():
    """A column of mixed content still has to sort, deterministically."""
    rows = [{"v": "text"}, {"v": 3}, {"v": None}, {"v": date(2026, 1, 1)}]
    first = [r["v"] for r in sort_records(rows, "v")]
    second = [r["v"] for r in sort_records(list(reversed(rows)), "v")]
    assert first == second
    assert first[-1] is None
