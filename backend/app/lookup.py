"""The ServiceTitan lookup card — Phase 4.

Who is this email from, as far as ServiceTitan knows? Built on demand when a
message is opened, shown in the detail pane, and that is the whole of where
it goes: never into a prompt, never into the training signal. The API terms
forbid both, and cap caching at 24 hours — so the card lives on the message
row for at most a day and the worker clears anything older. The reasoning is
the ServiceTitan entry in docs/decisions.md.

Matching, in order:

  1. **Phone.** Any number in the message — signatures, mostly — is looked up
     against customers' contact numbers. ServiceTitan has no email filter,
     so this is the reliable path.
  2. **Name, verified by email.** The sender's display name finds candidates;
     one counts only if its contacts include the sender's address. A name
     alone never matches — too many Smiths.

Property-manager and HOA mail will match the manager, not the occupant with
the problem. The card says what it matched on so nobody has to guess.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import update
from sqlalchemy.orm import Session

from .config import settings
from .db import as_utc, utcnow
from .models import Message
from .schemas import StCard, StContact, StCustomer, StJob, StMatch, StMembership
from .servicetitan import (
    OPEN_JOB_STATUSES,
    ServiceTitanClient,
    ServiceTitanError,
    find_phones,
)

log = logging.getLogger(__name__)

# The API terms' ceiling on caching ServiceTitan content. A constant, not a
# setting: nothing in config should be able to raise it.
CARD_MAX_AGE = timedelta(hours=24)

# Caps on how much one card may cost in API calls.
MAX_PHONES = 4
MAX_NAME_CANDIDATES = 8
MAX_OPEN_JOBS_WITH_APPOINTMENTS = 5
RECENT_JOBS = 3


class Lookups(Protocol):
    """What build_card needs from a client. ServiceTitanClient satisfies it;
    tests hand in a fake."""

    def find_customers_by_phone(self, phone: str) -> list[dict[str, Any]]: ...
    def find_customers_by_name(self, name: str) -> list[dict[str, Any]]: ...
    def customer_contacts(self, customer_id: int) -> list[dict[str, Any]]: ...
    def memberships(self, customer_id: int, status: str | None = None) -> list[dict[str, Any]]: ...
    def membership_types(self, ids: list[int]) -> list[dict[str, Any]]: ...
    def jobs(self, customer_id: int, limit: int = 20) -> list[dict[str, Any]]: ...
    def job_types(self, ids: list[int]) -> list[dict[str, Any]]: ...
    def appointments(self, job_id: int) -> list[dict[str, Any]]: ...


# --- shaping ServiceTitan's records -----------------------------------------


def _address(record: dict[str, Any]) -> str:
    address = record.get("address") or {}
    street = " ".join(p for p in (address.get("street"), address.get("unit")) if p)
    city_state = " ".join(p for p in (address.get("state"), address.get("zip")) if p)
    parts = [street, address.get("city"), city_state]
    return ", ".join(p for p in parts if p)


def _match(record: dict[str, Any]) -> StMatch:
    return StMatch(id=int(record["id"]), name=record.get("name") or "", address=_address(record))


def _customer(record: dict[str, Any], contacts: list[dict[str, Any]]) -> StCustomer:
    return StCustomer(
        id=int(record["id"]),
        name=record.get("name") or "",
        type=record.get("type"),
        address=_address(record),
        active=bool(record.get("active", True)),
        do_not_service=bool(record.get("doNotService", False)),
        contacts=[
            StContact(type=c.get("type") or "", value=c.get("value") or "")
            for c in contacts
            if c.get("value")
        ][:6],
    )


def _names(records: list[dict[str, Any]]) -> dict[int, str]:
    return {int(r["id"]): r.get("name") or "" for r in records if r.get("id") is not None}


def _next_appointment(appointments: list[dict[str, Any]], now: datetime) -> datetime | None:
    """The soonest upcoming visit; failing that, the latest one on the books."""
    starts: list[datetime] = []
    for appt in appointments:
        if appt.get("status") in ("Canceled", "Done"):
            continue
        raw = appt.get("start")
        if not raw:
            continue
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        starts.append(as_utc(when))
    if not starts:
        return None
    upcoming = [s for s in starts if s >= now]
    return min(upcoming) if upcoming else max(starts)


def _job(record: dict[str, Any], type_names: dict[int, str], next_appointment=None) -> StJob:
    type_id = record.get("jobTypeId")
    return StJob(
        id=int(record["id"]),
        number=str(record.get("jobNumber") or record.get("number") or record["id"]),
        type=type_names.get(int(type_id), "") if type_id is not None else "",
        status=record.get("jobStatus") or "",
        summary=(record.get("summary") or "")[:160],
        next_appointment=next_appointment,
        completed_on=record.get("completedOn") or None,
    )


def _membership(record: dict[str, Any], type_names: dict[int, str]) -> StMembership:
    type_id = record.get("membershipTypeId")
    return StMembership(
        id=int(record["id"]),
        type=type_names.get(int(type_id), "Membership") if type_id is not None else "Membership",
        status=record.get("status") or "",
        from_date=record.get("from") or None,
        to_date=record.get("to") or None,
    )


# --- the card ---------------------------------------------------------------


def build_card(
    st: Lookups, *, from_name: str, from_email: str, body: str
) -> StCard:
    """Everything the detail pane shows, from a handful of reads."""
    now = utcnow()
    phones = find_phones(body)[:MAX_PHONES]

    customers: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] | None = None
    matched_by: str | None = None
    matched_phone: str | None = None

    for phone in phones:
        found = st.find_customers_by_phone(phone)
        if found:
            customers, matched_by, matched_phone = found, "phone", phone
            break

    if not customers:
        email = (from_email or "").strip().lower()
        if email:
            for candidate in st.find_customers_by_name(from_name)[:MAX_NAME_CANDIDATES]:
                candidate_contacts = st.customer_contacts(candidate["id"])
                if any(
                    (c.get("type") or "") == "Email"
                    and (c.get("value") or "").strip().lower() == email
                    for c in candidate_contacts
                ):
                    customers, contacts, matched_by = [candidate], candidate_contacts, "name"
                    break

    if not customers:
        return StCard(status="unmatched", checked_at=now, phones_tried=len(phones))

    record = customers[0]
    customer_id = int(record["id"])
    if contacts is None:
        contacts = st.customer_contacts(customer_id)

    memberships = st.memberships(customer_id)
    membership_type_names = _names(
        st.membership_types(
            sorted({int(m["membershipTypeId"]) for m in memberships if m.get("membershipTypeId") is not None})
        )
    )

    jobs = st.jobs(customer_id)
    job_type_names = _names(
        st.job_types(
            sorted({int(j["jobTypeId"]) for j in jobs if j.get("jobTypeId") is not None})
        )
    )
    open_jobs = [j for j in jobs if j.get("jobStatus") in OPEN_JOB_STATUSES]
    finished = sorted(
        (j for j in jobs if j.get("jobStatus") == "Completed"),
        key=lambda j: j.get("completedOn") or "",
        reverse=True,
    )[:RECENT_JOBS]

    open_out: list[StJob] = []
    for i, job in enumerate(open_jobs):
        next_at = None
        if i < MAX_OPEN_JOBS_WITH_APPOINTMENTS:
            next_at = _next_appointment(st.appointments(int(job["id"])), now)
        open_out.append(_job(job, job_type_names, next_at))

    # Active first, then the rest — a lapsed membership is still worth a line.
    memberships_sorted = sorted(
        memberships, key=lambda m: (m.get("status") != "Active", m.get("from") or "")
    )

    return StCard(
        status="matched",
        checked_at=now,
        matched_by=matched_by,
        matched_phone=matched_phone,
        phones_tried=len(phones),
        customer=_customer(record, contacts),
        memberships=[_membership(m, membership_type_names) for m in memberships_sorted][:4],
        open_jobs=open_out,
        recent_jobs=[_job(j, job_type_names) for j in finished],
        other_matches=[_match(c) for c in customers[1:4]],
    )


# --- caching on the message row ----------------------------------------------


def card_for(db: Session, message: Message, *, refresh: bool = False) -> StCard:
    """The card for a message: cached if it's under a day old, built otherwise.

    An error builds nothing and caches nothing — the next open tries again.
    """
    if not settings.servicetitan_configured:
        return StCard(status="off")

    checked_at = as_utc(message.servicetitan_checked_at)
    if (
        not refresh
        and message.servicetitan_card
        and checked_at is not None
        and utcnow() - checked_at < CARD_MAX_AGE
    ):
        return StCard(**{**message.servicetitan_card, "cached": True})

    try:
        with ServiceTitanClient() as st:
            card = build_card(
                st,
                from_name=message.from_name,
                from_email=message.from_email,
                body=message.body_text or "",
            )
    except (ServiceTitanError, httpx.HTTPError) as exc:
        log.warning("ServiceTitan lookup for message %s failed: %s", message.id, exc)
        return StCard(status="error", checked_at=utcnow(), error=str(exc)[:200])

    message.servicetitan_card = card.model_dump(mode="json")
    message.servicetitan_checked_at = card.checked_at
    db.commit()
    return card


def expire_cards(db: Session) -> int:
    """Clear every card older than the ceiling. The worker runs this each
    cycle; it's what makes the 24-hour limit true rather than aspirational."""
    cutoff = utcnow() - CARD_MAX_AGE
    result = db.execute(
        update(Message)
        .where(Message.servicetitan_checked_at.isnot(None))
        .where(Message.servicetitan_checked_at < cutoff)
        .values(servicetitan_card=None, servicetitan_checked_at=None)
    )
    db.commit()
    return result.rowcount or 0
