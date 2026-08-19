"""Taking messages from Graph and putting them in the queue.

This is the only place that turns a parsed message into database rows. The
parsing (app/mail/) and the decision (app/mail/rules.py) are both pure and
tested on their own; what's left here is the writing.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classify import UNSORTED, Classification, classify_new
from .config import settings
from .db import utcnow
from .draft import draft_reply_text
from .graph import GraphClient, GraphError
from .mail.normalize import NormalizedMessage, normalize
from .mail.rules import Action, decide
from .privacy import load_patterns
from .models import (
    HANDLED,
    KIND_MODEL,
    OPEN,
    SOURCE_FORWARD,
    ClassificationEvent,
    MailboxState,
    Message,
    Note,
    User,
)

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    created: int = 0
    noted: int = 0
    skipped: int = 0
    failed: int = 0

    def __add__(self, other: "IngestResult") -> "IngestResult":
        return IngestResult(
            self.created + other.created,
            self.noted + other.noted,
            self.skipped + other.skipped,
            self.failed + other.failed,
        )

    def __str__(self) -> str:
        return (
            f"{self.created} created, {self.noted} noted, "
            f"{self.skipped} skipped, {self.failed} failed"
        )


def _parse_received(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return utcnow()


def _existing_conversation(db: Session, msg: NormalizedMessage) -> Message | None:
    """The queue item already tracking this thread, if there is one."""
    if not msg.conversation_id:
        return None
    return (
        db.execute(
            select(Message)
            .where(Message.conversation_id == msg.conversation_id)
            .order_by(Message.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _already_ingested(db: Session, graph_id: str) -> bool:
    if not graph_id:
        return False
    seen_message = db.execute(
        select(Message.id).where(Message.graph_message_id == graph_id).limit(1)
    ).first()
    if seen_message:
        return True
    seen_note = db.execute(
        select(Note.id).where(Note.graph_message_id == graph_id).limit(1)
    ).first()
    return bool(seen_note)


def _user_for_email(db: Session, email: str) -> User | None:
    if not email:
        return None
    return (
        db.execute(
            select(User).where(func.lower(User.email) == email.lower()).limit(1)
        )
        .scalars()
        .first()
    )


def create_message(
    db: Session,
    msg: NormalizedMessage,
    classification: Classification | None = None,
    draft: str | None = None,
) -> Message:
    """Write a new queue item, sorted by whatever the classifier decided.

    No classification (or a failed one) files it as unsorted Other at zero
    confidence — nothing looks confidently sorted when nothing has been
    sorted at all. A repeatedly-rejected sender arrives already handled, so
    known noise never hits the open queue.
    """
    c = classification or UNSORTED

    reasons: list[str] = []
    if msg.form_type:
        reasons.append(f"Submitted through the website ({msg.form_type}) form")
    if msg.source == SOURCE_FORWARD and msg.forwarded_by:
        reasons.append(f"Forwarded to the queue by {msg.forwarded_by}")
    if msg.needs_review:
        reasons.append(msg.review_reason)
    reasons.extend(c.reasons)

    # Who may see it if it's private: everyone the mail actually went to,
    # plus the mailbox it arrived in (BCC and distribution lists can keep
    # that address out of To/Cc). Stored comma-wrapped for exact matching.
    audience = {e for e in msg.to_recipients + msg.cc_recipients if e}
    audience.add(msg.mailbox.lower())

    record = Message(
        graph_message_id=msg.graph_message_id or None,
        conversation_id=msg.conversation_id,
        mailbox=msg.mailbox,
        from_name=msg.from_name or msg.from_email,
        from_email=msg.from_email,
        subject=msg.subject or "(no subject)",
        body_text=msg.body_text,
        body_html=msg.body_html,
        body_clean=msg.body_clean,
        received_at=_parse_received(msg.received_at),
        queue=c.queue,
        confidence=c.confidence,
        is_urgent=c.is_urgent,
        is_private=c.is_private,
        visible_to="," + ",".join(sorted(audience)) + ",",
        classification_reasons=reasons,
        draft_reply=draft,
        status=HANDLED if c.auto_handle else OPEN,
        handled_at=utcnow() if c.auto_handle else None,
        source=msg.source,
        forwarded_by=msg.forwarded_by,
        form_type=msg.form_type,
        attachment_count=msg.attachment_count,
        attachment_names=msg.attachment_names,
    )
    db.add(record)
    db.flush()

    # Every automatic classification is logged, same as a human correction.
    db.add(
        ClassificationEvent(
            message_id=record.id,
            from_queue=None,
            to_queue=c.queue,
            changed_by=None,
            confidence=c.confidence,
            kind=KIND_MODEL,
        )
    )
    return record


def add_note(db: Session, message: Message, msg: NormalizedMessage) -> Note:
    """Attach a threaded reply to an existing item as an internal note."""
    author = _user_for_email(db, msg.from_email)
    note = Note(
        message_id=message.id,
        user_id=author.id if author else None,
        author_name=msg.from_name or msg.from_email,
        body_text=msg.body_clean or msg.body_text,
        graph_message_id=msg.graph_message_id or None,
    )
    db.add(note)
    return note


def ingest_one(
    db: Session,
    raw: dict,
    mailbox: str,
    *,
    graph: GraphClient | None = None,
) -> str:
    """Process one raw Graph message. Returns the action taken."""
    if raw.get("isDraft"):
        return "skip"
    # A delta query reports deletions as stub objects; nothing to ingest.
    if raw.get("@removed"):
        return "skip"

    msg = normalize(
        raw,
        mailbox,
        website_senders=settings.website_sender_list,
        forward_mailbox=settings.forward_mailbox,
    )

    existing = _existing_conversation(db, msg)
    private_senders = load_patterns(db)

    # Only fetch headers when the sender is otherwise plausible — it's an extra
    # round trip per message and most mail doesn't need it.
    headers = None
    if graph and msg.graph_message_id and not existing:
        try:
            headers = graph.message_headers(mailbox, msg.graph_message_id)
        except GraphError:
            headers = None

    verdict = decide(
        msg,
        internal_domain=settings.internal_domain,
        website_senders=settings.website_sender_list,
        mailboxes=settings.mailbox_list,
        existing_message_id=existing.id if existing else None,
        existing_is_handled=bool(existing and existing.status != OPEN),
        already_ingested=_already_ingested(db, msg.graph_message_id),
        headers=headers,
        private_senders=private_senders,
    )

    if verdict.action is Action.SKIP:
        log.debug("skip %s: %s", msg.graph_message_id, verdict.reason)
        return "skip"

    if verdict.action is Action.NOTE and existing is not None:
        add_note(db, existing, msg)
        if verdict.reopen:
            existing.status = OPEN
            existing.handled_at = None
            existing.handled_by = None
        return "note"

    # Classify BEFORE the insert: the model call takes seconds, and holding a
    # SQLite write transaction across it locks the portal out (the first-sync
    # lesson). Reads don't block anyone under WAL.
    classification = classify_new(
        db,
        mailbox=mailbox,
        from_name=msg.from_name or msg.from_email,
        from_email=msg.from_email,
        subject=msg.subject or "(no subject)",
        body=msg.body_clean or msg.body_text,
    )

    # Draft a reply for the messages someone will actually answer — service
    # and sales. Other is overwhelmingly noise; anything there can be drafted
    # on demand from the composer. Same pre-insert rule as classification.
    # Private mail is never auto-drafted: its recipient can still ask for a
    # draft, but nothing pushes its content through a prompt unasked.
    draft = None
    if (
        classification.queue in ("service", "sales")
        and not classification.auto_handle
        and not classification.is_private
    ):
        draft = draft_reply_text(
            graph,
            from_name=msg.from_name or msg.from_email,
            from_email=msg.from_email,
            subject=msg.subject or "(no subject)",
            body=msg.body_clean or msg.body_text,
            mailbox=mailbox,
            private_senders=private_senders,
        )

    record = create_message(db, msg, classification, draft)
    _tag_in_outlook(graph, mailbox, msg.graph_message_id)
    log.info(
        "queued #%s from %s (%s) -> %s at %d%% [%s]",
        record.id,
        msg.from_email,
        mailbox,
        classification.queue,
        classification.confidence,
        classification.source,
    )
    return "create"


def _tag_in_outlook(graph: GraphClient | None, mailbox: str, graph_id: str) -> None:
    """Best effort. A tag that didn't stick must never block ingestion."""
    if not graph or not graph_id or not settings.outlook_category:
        return
    try:
        graph.set_categories(mailbox, graph_id, [settings.outlook_category])
    except GraphError as exc:
        log.warning("Could not tag %s in %s: %s", graph_id, mailbox, exc)


def _received_at(raw: dict) -> datetime | None:
    """Parse Graph's receivedDateTime; None when absent or malformed."""
    value = raw.get("receivedDateTime")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def poll_mailbox(db: Session, graph: GraphClient, mailbox: str) -> IngestResult:
    """Read one mailbox and file whatever is new."""
    state = (
        db.execute(select(MailboxState).where(MailboxState.mailbox == mailbox))
        .scalars()
        .first()
    )
    if state is None:
        state = MailboxState(mailbox=mailbox)
        db.add(state)

    state.last_polled_at = utcnow()
    # Commit before any Graph fetch — holding a write transaction across
    # network calls locks every other process out of SQLite.
    db.commit()
    result = IngestResult()

    cutoff = (
        utcnow() - timedelta(days=settings.ingest_max_age_days)
        if settings.ingest_max_age_days > 0
        else None
    )

    try:
        # The since filter bounds the FIRST sync of a mailbox to the ingest
        # window — a plain delta walk enumerates its entire history into
        # memory, half an hour and a gigabyte for a real inbox. Once a delta
        # link exists the filter is ignored; it also re-bounds the re-walk
        # after a delta link expires.
        first_sync = state.delta_link is None
        messages, delta_link = graph.delta_messages(
            mailbox,
            state.delta_link,
            since_iso=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ") if cutoff else None,
        )
        if first_sync:
            log.info(
                "%s: first sync — %d message(s) from the last %d day(s)",
                mailbox,
                len(messages),
                settings.ingest_max_age_days,
            )
    except GraphError as exc:
        state.last_error = str(exc)[:1000]
        state.consecutive_failures += 1
        db.commit()
        log.error("Polling %s failed: %s", mailbox, exc)
        return IngestResult(failed=1)

    aged_out = 0
    for raw in messages:
        if cutoff is not None:
            received = _received_at(raw)
            if received is not None and received < cutoff:
                aged_out += 1
                continue
        try:
            action = ingest_one(db, raw, mailbox, graph=graph)
            if action == "create":
                result.created += 1
            elif action == "note":
                result.noted += 1
            else:
                result.skipped += 1
            db.commit()
        except Exception as exc:  # one bad message must not stop the mailbox
            db.rollback()
            result.failed += 1
            log.exception("Could not ingest %s from %s: %s", raw.get("id"), mailbox, exc)

    if aged_out:
        result.skipped += aged_out
        log.info(
            "%s: skipped %d message(s) older than %d days",
            mailbox,
            aged_out,
            settings.ingest_max_age_days,
        )

    # Only advance the delta link once everything in this batch is committed.
    # Losing the batch is recoverable; skipping past it is not.
    if delta_link:
        state.delta_link = delta_link
    state.last_success_at = utcnow()
    state.last_error = None
    state.consecutive_failures = 0
    db.commit()

    return result


def poll_all(db: Session, graph: GraphClient) -> IngestResult:
    total = IngestResult()
    for mailbox in settings.mailbox_list:
        total = total + poll_mailbox(db, graph, mailbox)
    return total
