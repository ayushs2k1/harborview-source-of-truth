# Decisions

Why the system is built the way it is. Written as the work happens, trimmed to two pages
at the end.

## Determinism is enforced, not hoped for

The same files, decisions, and as-of date must give identical output in any file order.
Three things quietly break that, so each is handled in one place:

- **Hashing.** Every stable identifier is blake2b over canonical JSON (`sot/ids.py`).
  Python's builtin `hash()` is salted per process, so an id derived from it changes
  between runs. A test spawns two subprocesses with different `PYTHONHASHSEED` values and
  asserts the ids match.
- **Ordering.** Unordered collections are sorted with an explicit key before becoming
  output (`sot/canon.py`). Mixed-type columns still sort, rather than raising.
- **Float accumulation.** Hour totals are summed in sorted order and rounded once, so a
  reshuffled set of shift segments cannot change a weekly total.

## Provisional person IDs use the cluster, not the first record

The spec derives a provisional id from "the first record's" name, role, and facility.
First depends on which file was read first, which contradicts the reproducibility
principle. The lexicographically smallest key in the cluster is used instead: same
intent, and the id no longer moves when uploads arrive in a different order.

## Unknown is a value, not a missing boolean

Checks return `PASS`, `FAIL`, or `UNKNOWN` (`sot/tri.py`), with Kleene combinators. An
empty series is `UNKNOWN`, never vacuously true — "every worked day was covered by a
valid credential" must not pass when no days are on record, because the usual cause is a
source that failed to load. Reporting that as compliant is precisely the failure the
three-valued rule exists to prevent.

## One standardized table, with views for readability

`std_records` holds every standardized record keyed by a canonical *source role*
(roster, payroll, credentials, schedule), with pack-mapped fields in JSON. The spec's
`std_hr`, `std_payroll`, and `std_licenses` exist as views over it. This is what lets the
trucking pack reuse every node downstream of ingestion: its sources differ, the engine
does not. Packs map their raw columns onto one shared canonical vocabulary, so trucking's
`cdl_number` becomes `license_number` and `terminal` becomes `facility_code`.

## Sample data cannot leak into the engine

The judges supply their own files. Any sample name, id, or date compiled into `sot/`
would work for our demo and not for theirs, and would not necessarily fail loudly. A test
greps the engine for sample literals, identifier shapes, and every identifying value
found in the generated fixtures, and fails on a hit. `packs/`, `scripts/`, `data/`, and
`tests/` are exempt, because that is where sample values belong.

The application title is allowed to contain the client's name; a facility name is not.

## Dependencies

Exactly the libraries the spec lists, pinned to exact versions with a lockfile. No
workflow engine: the DAG executor is small enough to read in one sitting, and reading it
is part of what the judges are being asked to do.
