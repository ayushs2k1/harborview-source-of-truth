"""Rules about dates.

Compliance is judged as of the date of the work, not as of today. Somebody who worked
in March with a licence that lapsed in April was licensed when they worked; somebody
who worked in May with the same licence was not. Everything here turns on that
distinction, which is why the as-of date is a parameter rather than a call to the
clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sot.normalize.dates import is_month_end
from sot.rules.engine import RuleContext, evaluator
from sot.rules.model import Finding


def _worked_dates(context: RuleContext, person_id: str) -> list[date]:
    return sorted(
        {
            day.work_date
            for day in context.match.days
            if day.person_id == person_id and day.work_hours > 0
        }
    )


def _needs(context: RuleContext, person_id: str, credential_type: str) -> bool:
    """Whether any role this person works actually needs this credential."""
    roles = {day.role_code for day in context.match.days if day.person_id == person_id}
    roles |= {line.role_code for line in context.pay_lines if line.person_id == person_id}
    person = context.person(person_id)
    roles.add(getattr(person, "role_code", "") or "")
    return any(
        credential_type.upper() in context.role_requires_credential(role) for role in roles if role
    )


@evaluator("CREDENTIAL_EXPIRING", "CREDENTIAL_EXPIRED")
def credential_expiry(context: RuleContext) -> Iterable[Finding]:
    """Expired, or close enough that somebody has to act now."""
    windows = sorted(context.setting("expiry_windows_days", [90, 60, 30, 14]) or [90], reverse=True)
    widest = windows[0] if windows else 90

    for credential in context.credentials:
        if credential.expires_on is None or not credential.holder_id:
            continue
        days = (credential.expires_on - context.as_of).days
        display = context.display_name(credential.holder_id)
        active = _needs(context, credential.holder_id, credential.credential_type) and bool(
            _worked_dates(context, credential.holder_id)
        )
        shared = {
            "display_name": display,
            "credential_type": credential.credential_type or "credential",
            "number": credential.number,
            "expires_on": credential.expires_on,
        }

        if days < 0:
            yield Finding(
                "CREDENTIAL_EXPIRED",
                {
                    **shared,
                    "days_ago": -days,
                    "active_in_licensed_role": active,
                    "work_note": (
                        " They are still working in a role that requires it." if active else ""
                    ),
                },
                entities=(context.entity(credential.holder_id),),
                key_parts=(credential.credential_id,),
            )
        elif days <= widest:
            yield Finding(
                "CREDENTIAL_EXPIRING",
                {
                    **shared,
                    "days_left": days,
                    "recert_note": _recert_note(context, credential),
                },
                entities=(context.entity(credential.holder_id),),
                key_parts=(credential.credential_id,),
            )


def _recert_note(context: RuleContext, credential) -> str:
    """Who files the renewal, where the pack knows."""
    recert = context.setting("cna_recert", {}) or {}
    if not recert or (credential.credential_type or "").upper() != "CNA":
        return ""
    return " The employing facility files aide recertification."


@evaluator("WORKED_AFTER_EXPIRY", "SCHEDULED_AFTER_EXPIRY")
def work_after_expiry(context: RuleContext) -> Iterable[Finding]:
    """Shifts on the wrong side of an expiry date.

    Split by the as-of date: shifts already worked are a compliance breach that has
    happened, and shifts still to come are one that can still be prevented. They need
    different people to do different things, so they are different findings.
    """
    for credential in context.credentials:
        if credential.expires_on is None or not credential.holder_id:
            continue
        if not _needs(context, credential.holder_id, credential.credential_type):
            continue

        after = [
            day
            for day in context.match.days
            if day.person_id == credential.holder_id
            and day.work_hours > 0
            and day.work_date > credential.expires_on
            and credential.credential_type.upper()
            in context.role_requires_credential(day.role_code)
        ]
        if not after:
            continue

        worked = [day for day in after if day.work_date <= context.as_of]
        upcoming = [day for day in after if day.work_date > context.as_of]
        display = context.display_name(credential.holder_id)

        for code, group in (("WORKED_AFTER_EXPIRY", worked), ("SCHEDULED_AFTER_EXPIRY", upcoming)):
            if not group:
                continue
            facilities = sorted({day.facility_code for day in group if day.facility_code})
            yield Finding(
                code,
                {
                    "display_name": display,
                    "credential_type": credential.credential_type or "credential",
                    "expires_on": credential.expires_on,
                    "shift_count": len(group),
                    "facility": ", ".join(facilities) or "an unrecorded site",
                    "dates": ", ".join(f"{day.work_date:%b} {day.work_date.day}" for day in group),
                },
                entities=(context.entity(credential.holder_id),),
                key_parts=(credential.credential_id, code),
            )


@evaluator("VERIFICATION_STALE", "VERIFIED_DATE_IN_FUTURE")
def verification_age(context: RuleContext) -> Iterable[Finding]:
    """How long since anybody actually checked."""
    limit = int(context.setting("verification_max_age_days", 60) or 60)
    for credential in context.credentials:
        if credential.last_verified is None or not credential.holder_id:
            continue
        age = (context.as_of - credential.last_verified).days
        display = context.display_name(credential.holder_id)
        if age < 0:
            yield Finding(
                "VERIFIED_DATE_IN_FUTURE",
                {
                    "display_name": display,
                    "credential_type": credential.credential_type or "credential",
                    "last_verified": credential.last_verified,
                    "as_of": context.as_of,
                },
                entities=(context.entity(credential.holder_id),),
                key_parts=(credential.credential_id,),
            )
        elif age > limit:
            yield Finding(
                "VERIFICATION_STALE",
                {
                    "display_name": display,
                    "credential_type": credential.credential_type or "credential",
                    "last_verified": credential.last_verified,
                    "age_days": age,
                    "max_age_days": limit,
                },
                entities=(context.entity(credential.holder_id),),
                key_parts=(credential.credential_id,),
            )


@evaluator("CNA_EXPIRY_NOT_MONTH_END")
def aide_expiry_shape(context: RuleContext) -> Iterable[Finding]:
    """New York aide renewals fall on month ends; anything else is a typing error."""
    recert = context.setting("cna_recert", {}) or {}
    if not recert.get("expiry_on_month_end"):
        return
    for credential in context.credentials:
        if (credential.credential_type or "").upper() != "CNA":
            continue
        if credential.expires_on is None or is_month_end(credential.expires_on):
            continue
        yield Finding(
            "CNA_EXPIRY_NOT_MONTH_END",
            {
                "display_name": context.display_name(credential.holder_id),
                "expires_on": credential.expires_on,
            },
            entities=(context.entity(credential.holder_id),) if credential.holder_id else (),
            key_parts=(credential.credential_id,),
        )
