"""The expiration radar.

The client's third problem, in their words: "licenses, certifications, and vendor
paperwork expire, and we usually find out too late." Finding out too late is a
reporting problem, not a records problem - the dates were always there, nobody was
looking at all of them at once.

So this is one list, sorted by urgency, covering every credential and every vendor
document, with the two things a date alone cannot tell you: whether anybody has
actually worked on the wrong side of it, and whether the renewal can be supported by
the hours we hold.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sot.canon import sum_hours

BAND_EXPIRED = "EXPIRED"
BAND_OK = "OK"

HOLDER_PERSON = "person"
HOLDER_ORG = "org"


@dataclass
class ExpiryRow:
    """One thing that expires."""

    holder_type: str
    holder_id: str
    holder: str
    credential_type: str
    number: str = ""
    facility: str = ""
    expires_on: date | None = None
    days_left: int | None = None
    band: str = BAND_OK
    last_verified: date | None = None
    verified_age_days: int | None = None
    verification_stale: bool = False
    #: The first rostered shift falling after the expiry date, if there is one.
    next_shift_after_expiry: date | None = None
    shifts_worked_after_expiry: int = 0
    #: New York aide recertification: paid aide hours found against hours required.
    recert_hours_found: float | None = None
    recert_hours_required: float | None = None

    @property
    def recert_ready(self) -> bool | None:
        if self.recert_hours_required is None or self.recert_hours_found is None:
            return None
        return self.recert_hours_found >= self.recert_hours_required

    @property
    def urgency(self) -> tuple:
        """Sort key. Expired first, then soonest, then whoever is still working."""
        return (
            0 if self.band == BAND_EXPIRED else 1,
            self.days_left if self.days_left is not None else 10_000,
            -self.shifts_worked_after_expiry,
            self.holder,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "holder_type": self.holder_type,
            "holder_id": self.holder_id,
            "holder": self.holder,
            "credential_type": self.credential_type,
            "number": self.number,
            "facility": self.facility,
            "expires_on": self.expires_on.isoformat() if self.expires_on else None,
            "days_left": self.days_left,
            "band": self.band,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
            "verified_age_days": self.verified_age_days,
            "verification_stale": self.verification_stale,
            "next_shift_after_expiry": (
                self.next_shift_after_expiry.isoformat() if self.next_shift_after_expiry else None
            ),
            "shifts_worked_after_expiry": self.shifts_worked_after_expiry,
            "recert_hours_found": self.recert_hours_found,
            "recert_hours_required": self.recert_hours_required,
            "recert_ready": self.recert_ready,
        }


@dataclass
class ExpirationView:
    rows: list[ExpiryRow] = field(default_factory=list)
    as_of: date | None = None
    windows: tuple[int, ...] = ()

    def filtered(
        self, *, band: str | None = None, facility: str | None = None, kind: str | None = None
    ) -> list[ExpiryRow]:
        return [
            row
            for row in self.rows
            if (band is None or row.band == band)
            and (facility is None or row.facility == facility)
            and (kind is None or row.credential_type.upper() == kind.upper())
        ]

    def counts_by_band(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.band] = counts.get(row.band, 0) + 1
        return counts

    @property
    def needs_attention(self) -> list[ExpiryRow]:
        """Anything expired or inside the widest window."""
        return [row for row in self.rows if row.band != BAND_OK]


def band_for(days_left: int | None, windows: Sequence[int]) -> str:
    """Which urgency band a date falls in.

    The bands come from the pack, so a facility that wants to start chasing renewals
    at 120 days changes a list rather than the code.
    """
    if days_left is None:
        return BAND_OK
    if days_left < 0:
        return BAND_EXPIRED
    for window in sorted(windows):
        if days_left <= window:
            return f"{window}d"
    return BAND_OK


def build_expirations(
    *,
    credentials: Sequence[Any],
    as_of: date,
    pack: Any,
    display_names: Mapping[str, str] | None = None,
    facilities: Mapping[str, str] | None = None,
    person_days: Sequence[Any] = (),
    pay_lines: Sequence[Any] = (),
    vendor_records: Sequence[Mapping[str, Any]] = (),
) -> ExpirationView:
    """Every expiring thing, in one list, sorted by urgency."""
    display_names = display_names or {}
    facilities = facilities or {}
    windows = tuple(pack.setting("expiry_windows_days", [90, 60, 30, 14]) or [90])
    max_age = int(pack.setting("verification_max_age_days", 60) or 60)
    recert = pack.setting("cna_recert", {}) or {}
    aide_roles = {
        str(role).upper() for role in (pack.setting("role_families", {}) or {}).get("aide", ())
    }

    view = ExpirationView(as_of=as_of, windows=windows)

    for credential in sorted(credentials, key=lambda item: item.credential_id):
        days = (credential.expires_on - as_of).days if credential.expires_on else None
        age = (as_of - credential.last_verified).days if credential.last_verified else None
        after = sorted(
            day.work_date
            for day in person_days
            if day.person_id == credential.holder_id
            and credential.expires_on
            and day.work_date > credential.expires_on
            and day.work_hours > 0
        )
        row = ExpiryRow(
            holder_type=HOLDER_PERSON,
            holder_id=credential.holder_id,
            holder=display_names.get(credential.holder_id, credential.holder_id),
            credential_type=credential.credential_type or "credential",
            number=credential.number,
            facility=facilities.get(credential.holder_id, ""),
            expires_on=credential.expires_on,
            days_left=days,
            band=band_for(days, windows),
            last_verified=credential.last_verified,
            verified_age_days=age,
            verification_stale=age is not None and age > max_age,
            next_shift_after_expiry=next((d for d in after if d > as_of), None),
            shifts_worked_after_expiry=sum(1 for d in after if d <= as_of),
        )
        _add_recert(row, credential, recert, aide_roles, pay_lines)
        view.rows.append(row)

    view.rows.extend(_vendor_rows(vendor_records, as_of, windows, max_age))
    view.rows.sort(key=lambda row: row.urgency)
    return view


def _add_recert(
    row: ExpiryRow,
    credential: Any,
    recert: Mapping[str, Any],
    aide_roles: set[str],
    pay_lines: Sequence[Any],
) -> None:
    """Whether the payroll we hold could support an aide's renewal.

    Reported as evidence available rather than as fact: the hours may well exist in an
    export nobody sent us, and the distinction matters because the employer is the one
    who files.
    """
    required = float(recert.get("min_paid_hours", 0) or 0)
    if required <= 0 or (credential.credential_type or "").upper() != "CNA":
        return
    if credential.expires_on is None:
        return
    months = int(recert.get("period_months", 24) or 24)
    window_start = credential.expires_on - timedelta(days=int(months * 30.44))
    row.recert_hours_required = required
    row.recert_hours_found = sum_hours(
        line.hours_paid
        for line in pay_lines
        if line.person_id == credential.holder_id
        and line.role_code.upper() in aide_roles
        and line.period_end
        and window_start <= line.period_end <= credential.expires_on
    )


def _vendor_rows(
    records: Sequence[Mapping[str, Any]], as_of: date, windows: Sequence[int], max_age: int
) -> list[ExpiryRow]:
    """Vendor paperwork, modelled as credentials held by an organisation.

    The same model, which is the point of making a credential its own entity rather
    than a column on a person.
    """
    rows: list[ExpiryRow] = []
    for record in records:
        try:
            payload = json.loads(record.get("payload_json") or "{}")
        except (TypeError, ValueError):
            continue
        expires = _as_date(payload.get("expires_on"))
        verified = _as_date(payload.get("verified_on"))
        days = (expires - as_of).days if expires else None
        age = (as_of - verified).days if verified else None
        vendor = str(payload.get("vendor") or "").strip()
        if not vendor:
            continue
        rows.append(
            ExpiryRow(
                holder_type=HOLDER_ORG,
                holder_id=vendor,
                holder=vendor,
                credential_type=str(payload.get("doc_type") or "document"),
                number=str(payload.get("doc_number") or ""),
                expires_on=expires,
                days_left=days,
                band=band_for(days, windows),
                last_verified=verified,
                verified_age_days=age,
                verification_stale=age is not None and age > max_age,
            )
        )
    return rows


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
