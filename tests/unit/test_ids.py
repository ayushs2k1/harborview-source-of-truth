"""Stable identifiers. These must not move between runs, processes, or machines."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from sot.ids import (
    digest,
    file_id,
    flag_id,
    person_id_from_employee_id,
    provisional_person_id,
    record_fingerprint,
    run_id,
    stable_id,
)


def test_digest_is_stable_for_equivalent_payloads():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


def test_digest_differs_for_different_payloads():
    assert digest({"a": 1}) != digest({"a": 2})


def test_stable_id_is_prefixed_and_fixed_width():
    value = stable_id("FG", {"x": 1})
    prefix, _, body = value.partition("-")
    assert prefix == "FG"
    assert len(body) == 16
    assert set(body) <= set("0123456789abcdef")


def test_ids_survive_a_different_hash_seed():
    """The whole point of not using Python's builtin hash().

    PYTHONHASHSEED randomizes str hashing per process. An id derived from it would
    change between runs, breaking flag de-duplication and every stored decision. Two
    subprocesses with deliberately different seeds must agree.
    """
    program = (
        "from sot.ids import flag_id, provisional_person_id;"
        "print(flag_id('X', ['p1'], ['v']));"
        "print(provisional_person_id([{'name_key':'n','role_code':'R','facility_code':'F'}]))"
    )
    outputs = []
    for seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, env=env, check=True
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_flag_id_ignores_entity_and_evidence_order():
    a = flag_id("HOURS_VARIANCE", ["p2", "p1"], ["36", "40"])
    b = flag_id("HOURS_VARIANCE", ["p1", "p2"], ["40", "36"])
    assert a == b


def test_flag_id_separates_different_rules_on_the_same_entity():
    assert flag_id("A", ["p1"], ["v"]) != flag_id("B", ["p1"], ["v"])


def test_flag_id_excludes_the_run():
    """A flag keeps its identity across runs, which is what lets a dismissal stick."""
    before = flag_id("CREDENTIAL_EXPIRING", ["p1"], ["2026-12-31"])
    after = flag_id("CREDENTIAL_EXPIRING", ["p1"], ["2026-12-31"])
    assert before == after


def test_file_id_follows_content_not_name():
    assert file_id("abc123") == file_id("abc123")
    assert file_id("abc123") != file_id("def456")


def test_person_id_from_employee_id_is_normalized():
    assert person_id_from_employee_id(" e42 ") == person_id_from_employee_id("E42")


def test_provisional_person_id_ignores_member_order():
    """Spec section 9 says 'the first record'; first depends on which file was read
    first, so the cluster's smallest key is used instead. Same id either way."""
    members = [
        {"name_key": "zeta", "role_code": "R2", "facility_code": "F2"},
        {"name_key": "alpha", "role_code": "R1", "facility_code": "F1"},
    ]
    assert provisional_person_id(members) == provisional_person_id(list(reversed(members)))


def test_provisional_person_id_uses_the_smallest_key():
    members = [
        {"name_key": "zeta", "role_code": "R2", "facility_code": "F2"},
        {"name_key": "alpha", "role_code": "R1", "facility_code": "F1"},
    ]
    only_smallest = [{"name_key": "alpha", "role_code": "R1", "facility_code": "F1"}]
    assert provisional_person_id(members) == provisional_person_id(only_smallest)


def test_provisional_person_id_needs_a_member():
    with pytest.raises(ValueError):
        provisional_person_id([])


def test_record_fingerprint_ignores_row_position():
    """Spec section 16: a re-export shifts every row, and accepted matches must survive."""
    a = record_fingerprint("payroll", "bell marcus", "CNA", "F1")
    b = record_fingerprint("payroll", "bell marcus", "CNA", "F1")
    assert a == b


def test_record_fingerprint_separates_sources():
    assert record_fingerprint("payroll", "n", "R", "F") != record_fingerprint("hr", "n", "R", "F")


def test_record_fingerprint_treats_missing_role_and_facility_as_empty():
    assert record_fingerprint("hr", "n", None, None) == record_fingerprint("hr", "n", "", "")


def test_run_id_is_sortable_and_carries_the_input_digest():
    first = run_id("abcd1234ef", "2026-09-21T10:00:00")
    second = run_id("abcd1234ef", "2026-09-21T11:00:00")
    assert first < second
    assert first.endswith("abcd1234")
    assert "T" in first
