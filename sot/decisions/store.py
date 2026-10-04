"""Reading human decisions back.

A decision is the memory of the system: somebody looked at a borderline match and
settled it, and that answer has to survive the next export, the next run, and the next
re-import of the same file. Which is why decisions are keyed on a fingerprint of the
record's content rather than on where it sat in a file.

Writing decisions is the subject of phase 8; this is what every run reads at the start.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sot.ids import digest
from sot.store.db import Database

ACCEPT_MATCH = "ACCEPT_MATCH"
REJECT_MATCH = "REJECT_MATCH"
CODE_MAP = "CODE_MAP"
HEADER_MAP = "HEADER_MAP"
DISMISS_FLAG = "DISMISS_FLAG"
NOTE = "NOTE"


@dataclass
class DecisionSet:
    """Every decision in force for a run."""

    #: Record fingerprint -> the person it was confirmed to be.
    accepted: dict[str, str] = field(default_factory=dict)
    #: Pairs a human has ruled out.
    rejected: set[tuple[str, str]] = field(default_factory=set)
    #: Crosswalk name -> folded raw value -> canonical code.
    code_maps: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Source -> folded heading -> canonical column.
    header_maps: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Flags a human has set aside, with the reason.
    dismissed: dict[str, str] = field(default_factory=dict)

    def accepted_person(self, fingerprint: str) -> str | None:
        return self.accepted.get(fingerprint)

    def is_rejected(self, fingerprint: str, person_id: str) -> bool:
        return (fingerprint, person_id) in self.rejected

    @property
    def digest(self) -> str:
        """Content hash of the decisions in force, recorded against the run.

        Two runs over the same files that disagree should be explainable, and the
        usual explanation is that somebody made a decision in between.
        """
        return digest(
            {
                "accepted": sorted(self.accepted.items()),
                "rejected": sorted(self.rejected),
                "code_maps": {k: sorted(v.items()) for k, v in sorted(self.code_maps.items())},
                "header_maps": {k: sorted(v.items()) for k, v in sorted(self.header_maps.items())},
                "dismissed": sorted(self.dismissed),
            }
        )

    def __len__(self) -> int:
        return (
            len(self.accepted)
            + len(self.rejected)
            + len(self.dismissed)
            + sum(len(v) for v in self.code_maps.values())
            + sum(len(v) for v in self.header_maps.values())
        )


def load_decisions(db: Database) -> DecisionSet:
    """Every active decision, newest last so a later one overrides an earlier one."""
    decisions = DecisionSet()
    rows = db.query(
        "SELECT decision_type, key_json, value_json FROM decisions "
        "WHERE active ORDER BY created_at, decision_id"
    )
    for row in rows:
        try:
            key = json.loads(row["key_json"] or "{}")
            value = json.loads(row["value_json"] or "{}")
        except (TypeError, ValueError):
            continue
        kind = row["decision_type"]

        if kind == ACCEPT_MATCH and key.get("fingerprint") and value.get("person_id"):
            decisions.accepted[key["fingerprint"]] = value["person_id"]
        elif kind == REJECT_MATCH and key.get("fingerprint") and value.get("person_id"):
            decisions.rejected.add((key["fingerprint"], value["person_id"]))
        elif kind == CODE_MAP and key.get("crosswalk") and key.get("raw"):
            decisions.code_maps.setdefault(key["crosswalk"], {})[key["raw"]] = value.get("code", "")
        elif kind == HEADER_MAP and key.get("source") and key.get("header"):
            decisions.header_maps.setdefault(key["source"], {})[key["header"]] = value.get(
                "column", ""
            )
        elif kind == DISMISS_FLAG and key.get("flag_id"):
            decisions.dismissed[key["flag_id"]] = value.get("reason", "")
    return decisions
