"""Deciding what to do with a message the poller found.

Three outcomes:

  CREATE  a new queue item
  NOTE    attach it to an item that already exists, as an internal note
  SKIP    ignore it entirely

This is kept separate from the database so the decisions can be tested on
their own. `decide()` takes plain facts and returns a verdict; the caller does
the writing.

The rule that matters most: **website@expertsvc.com is not internal.** Skipping
our own domain is right for office chatter and catastrophic for the website
forms, which are the highest-intent mail the business gets.
"""

import re
from dataclasses import dataclass
from enum import Enum

from .normalize import NormalizedMessage


class Action(Enum):
    CREATE = "create"
    NOTE = "note"
    SKIP = "skip"


@dataclass
class Verdict:
    action: Action
    reason: str
    # For NOTE: which existing message it belongs to.
    message_id: int | None = None
    # For NOTE from a customer: bring a handled item back into the queue.
    reopen: bool = False


# Local parts that never represent a person expecting an answer.
_AUTOMATED_LOCAL_PARTS = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|postmaster|mailer-daemon|bounce|"
    r"notifications?|alerts?|automated|noreply)\b",
    re.IGNORECASE,
)

# Bulk mail headers worth trusting when Graph gives them to us.
_BULK_HEADERS = {"list-unsubscribe", "list-id", "precedence"}


def is_automated(from_email: str, headers: dict | None = None) -> bool:
    """Does this look like a robot rather than a customer?"""
    local = (from_email or "").split("@")[0]
    if _AUTOMATED_LOCAL_PARTS.match(local):
        return True

    lowered = {k.lower(): (v or "").lower() for k, v in (headers or {}).items()}
    if "list-unsubscribe" in lowered or "list-id" in lowered:
        return True
    if lowered.get("precedence") in {"bulk", "junk", "list"}:
        return True
    return False


def is_internal(msg: NormalizedMessage, internal_domain: str, website_senders) -> bool:
    """Office chatter — but never the website, which only looks internal."""
    if msg.from_email in set(website_senders):
        return False
    if msg.source == "forwarded":
        # A colleague put this here on purpose. The point is the customer
        # inside it, not the colleague who pressed Forward.
        return False
    return msg.sender_domain == (internal_domain or "").lower()


def addressed_to_us(msg: NormalizedMessage, mailboxes) -> bool:
    """Is a monitored mailbox in To or Cc?

    Cc counts. One real sample had Craig only on Cc — a resident reported a
    leak to their HOA manager, who forwarded it to the builder and copied him.
    Checking To alone would have missed a live leak.
    """
    known = {m.lower() for m in mailboxes}
    if not known:
        return True
    recipients = set(msg.to_recipients) | set(msg.cc_recipients)
    if recipients & known:
        return True
    # Distribution lists and BCC mean the mailbox may appear nowhere in the
    # headers. It still arrived in that mailbox, so it still counts.
    return msg.mailbox.lower() in known


def decide(
    msg: NormalizedMessage,
    *,
    internal_domain: str,
    website_senders,
    mailboxes,
    existing_message_id: int | None = None,
    existing_is_handled: bool = False,
    already_ingested: bool = False,
    headers: dict | None = None,
) -> Verdict:
    """Work out what should happen to this message.

    `existing_message_id` is the queue item already tracking this
    conversation_id, if there is one — the caller looks that up.
    """
    if already_ingested:
        # The same email arriving in several monitored mailboxes is the normal
        # case here, not an edge case.
        return Verdict(Action.SKIP, "Already in the queue (seen in another mailbox).")

    if is_automated(msg.from_email, headers):
        return Verdict(Action.SKIP, f"Automated sender ({msg.from_email}).")

    internal = is_internal(msg, internal_domain, website_senders)

    if existing_message_id is not None:
        # Something in this thread is already in the queue. Whoever is
        # speaking, this belongs on that item rather than beside it.
        if internal:
            return Verdict(
                Action.NOTE,
                "Internal reply on an existing thread.",
                message_id=existing_message_id,
            )
        return Verdict(
            Action.NOTE,
            "Customer replied on an existing thread.",
            message_id=existing_message_id,
            # A customer writing again needs someone to look, even if the item
            # was closed.
            reopen=existing_is_handled,
        )

    if internal:
        # Office mail with no queue item to attach to. Not a customer request.
        return Verdict(Action.SKIP, f"Internal sender ({msg.from_email}).")

    if not addressed_to_us(msg, mailboxes):
        return Verdict(Action.SKIP, "No monitored mailbox in To or Cc.")

    if not msg.from_email:
        return Verdict(Action.SKIP, "No usable sender address.")

    return Verdict(Action.CREATE, "New customer request.")
