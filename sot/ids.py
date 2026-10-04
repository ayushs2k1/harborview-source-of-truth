"""Stable identifiers.

Every identifier that has to survive a restart, a re-run, or a different machine is
built here with blake2b over canonical JSON. Python's builtin ``hash()`` is salted per
process (PYTHONHASHSEED), so an id derived from it would change between runs and
silently break flag de-duplication and decision memory. It is never used.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from sot.canon import canonical_bytes

#: Chunk size for hashing files off disk.
_CHUNK = 1024 * 1024


def digest(payload: Any, *, size: int = 8) -> str:
    """Hex blake2b digest of ``payload`` in canonical form.

    ``size`` is in bytes, so the default yields 16 hex characters: short enough to read
    in a URL, wide enough that collisions are not a practical concern at our scale.
    """
    return hashlib.blake2b(canonical_bytes(payload), digest_size=size).hexdigest()


def stable_id(prefix: str, payload: Any, *, size: int = 8) -> str:
    """Prefixed stable id, e.g. ``F-1a2b3c4d5e6f7a8b``."""
    return f"{prefix}-{digest(payload, size=size)}"


def file_sha256(path: str | Path) -> str:
    """SHA-256 of a file's bytes, streamed so large PDFs do not land in memory."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def file_id(sha256: str) -> str:
    """Identifier for a landed file, derived only from its content.

    Two uploads of the same bytes under different names are the same file, which is
    what makes ``FILE_DUPLICATE`` detectable and double counting impossible.
    """
    return stable_id("FL", {"sha256": sha256})


def flag_id(rule_code: str, entity_keys: Iterable[str], evidence_values: Iterable[Any]) -> str:
    """Identifier for a flag, per spec section 12.

    Deliberately excludes ``run_id``, row numbers, and timestamps so that the same
    problem in the same data keeps the same id across runs. That is what lets a
    dismissal stick and what makes ``first_seen_run`` meaningful.
    """
    payload = {
        "rule": rule_code,
        "entities": sorted(str(key) for key in entity_keys),
        "evidence": sorted(str(value) for value in evidence_values),
    }
    return stable_id("FG", payload)


def person_id_from_employee_id(employee_id: str) -> str:
    """Stable person id for a roster record that carries its own identifier."""
    return f"P-{employee_id.strip().upper()}"


def provisional_person_id(members: Iterable[Mapping[str, Any]]) -> str:
    """Stable person id for a cluster with no employer-issued identifier.

    The spec describes hashing "the first record's" name, role, and facility. First-seen
    order depends on which file was read first, which would violate the reproducibility
    principle, so the cluster's lexicographically smallest key is used instead. Same
    intent, and the id no longer moves when the uploads arrive in a different order.
    """
    keys = sorted(
        (
            str(member.get("name_key") or ""),
            str(member.get("role_code") or ""),
            str(member.get("facility_code") or ""),
        )
        for member in members
    )
    if not keys:
        raise ValueError("provisional person id needs at least one member record")
    name_key, role_code, facility_code = keys[0]
    return stable_id("PP", {"name": name_key, "role": role_code, "facility": facility_code})


def record_fingerprint(
    source_type: str, name_key: str, role_code: str | None, facility_code: str | None
) -> str:
    """Identity of a source record for decision memory, per spec section 16.

    Excludes row numbers on purpose: a re-export of the same roster shifts every row,
    and an accepted match must survive that.
    """
    return stable_id(
        "RF",
        {
            "source": source_type,
            "name": name_key,
            "role": role_code or "",
            "facility": facility_code or "",
        },
    )


def run_id(input_digest: str, started_at_iso: str) -> str:
    """Identifier for one execution.

    Carries the timestamp so runs sort chronologically, plus a slice of the input digest
    so two runs over the same inputs are visibly related. Never used as a hash input
    anywhere else: derived content must not depend on which run produced it.

    Resolved to the millisecond rather than the second. Re-running the same files is
    the normal case - it is what the rerun button does - and at one-second resolution
    the second run would collide with the first.
    """
    stamp, _, fraction = started_at_iso.partition(".")
    stamp = stamp.replace("-", "").replace(":", "")
    millis = (fraction or "000000")[:3].ljust(3, "0")
    return f"R-{stamp}{millis}-{input_digest[:8]}"
