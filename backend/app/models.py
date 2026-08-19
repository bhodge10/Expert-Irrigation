"""Database tables.

Four tables carry the product plus one for login sessions:

  users                  the five office people
  messages               one row per inbound customer email
  replies                one row per reply a human sent
  classification_events  every automatic sort and every human correction
  private_senders        addresses and domains whose mail never enters
  sessions               server-side login sessions

classification_events is the record of what the model gets wrong. It is what
makes the classification prompt improvable later, so nothing writes a queue
change without also writing one of these.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow

# queue values. Service and sales are confident, dispatchable work. Anything
# the sorter can't confidently place — or real mail that's neither, like a
# billing question — waits in undetermined for a human. Ignored is mail the
# sorter is confident nobody needs to read or answer (marketing, receipts,
# automated notices); visible and reviewable, never deleted.
SERVICE = "service"
SALES = "sales"
UNDETERMINED = "undetermined"
IGNORED = "ignored"
QUEUES = (SERVICE, SALES, UNDETERMINED, IGNORED)

# status values
OPEN = "open"
HANDLED = "handled"
STATUSES = (OPEN, HANDLED)

# how a message got into the queue
SOURCE_GRAPH = "graph"  # polled straight from a monitored mailbox
SOURCE_FORWARD = "forwarded"  # staff forwarded it to the queue address
SOURCE_MANUAL = "manual"  # someone typed it in — phone call, walk-in
SOURCES = (SOURCE_GRAPH, SOURCE_FORWARD, SOURCE_MANUAL)

# which website form produced it, when it was a form at all
FORM_CONTACT = "contact"
FORM_INSTALL = "install"
FORM_SERVICE = "service_request"
FORM_TYPES = (FORM_CONTACT, FORM_INSTALL, FORM_SERVICE)

# what a classification event records. The model speaks once; every human
# action after that is a verdict on whether it was right.
KIND_MODEL = "model"  # the automatic sort itself
KIND_CORRECTION = "correction"  # a human moved it to another queue
KIND_CONFIRMATION = "confirmation"  # a human worked it where it landed
KIND_REJECTION = "rejection"  # a human said it shouldn't be here at all
EVENT_KINDS = (KIND_MODEL, KIND_CORRECTION, KIND_CONFIRMATION, KIND_REJECTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    initials: Mapped[str] = mapped_column(String(4))
    color: Mapped[str] = mapped_column(String(9))  # hex, e.g. #1F7A47
    role: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Graph identifiers. Nullable in Phase 1 because seeded fixtures have no
    # Microsoft origin; Phase 2 fills them in and dedupes on graph_message_id.
    graph_message_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(255), index=True)

    # The monitored mailbox it arrived at. Replies go out from here.
    mailbox: Mapped[str] = mapped_column(String(255), index=True)

    # The customer. For website forms this is dug out of the body, because the
    # form itself is sent by website@expertsvc.com — see docs/mail-patterns.md.
    from_name: Mapped[str] = mapped_column(String(255))
    from_email: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(500))

    # Full text as received, quoting and signatures and all. This is what the
    # office reads.
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_html: Mapped[str | None] = mapped_column(Text)

    # The same message with quoted history, signatures and form boilerplate
    # removed. This is what the classifier sees. Stored rather than recomputed
    # so that when a classification looks wrong you can see what it was given.
    body_clean: Mapped[str] = mapped_column(Text, default="")

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )

    # How it arrived, and from whom if a human put it here.
    source: Mapped[str] = mapped_column(String(16), default=SOURCE_GRAPH, index=True)
    forwarded_by: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Which website form this came from, if any.
    form_type: Mapped[str | None] = mapped_column(String(20))

    # We don't store attachments, only the fact of them — a leak report with a
    # photo is worth opening before one without.
    attachment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attachment_names: Mapped[list[str]] = mapped_column(JSON, default=list)

    queue: Mapped[str] = mapped_column(String(16), index=True, default=UNDETERMINED)
    confidence: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    classification_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Personal or confidential mail — payroll, HR, legal, family. Flagged by
    # the classifier (or a person), and then visible only to the logins whose
    # email appears in visible_to. Kept out of few-shot examples and never
    # auto-drafted, so its content stays out of every prompt.
    is_private: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    # Everyone the email actually went to (To + Cc + the mailbox it arrived
    # in), lowercase, wrapped in commas for exact LIKE matching:
    # ",craigz@expertsvc.com,megank@expertsvc.com,". Computed for every
    # message; only consulted when is_private is set.
    visible_to: Mapped[str | None] = mapped_column(Text)

    # A reply drafted in Craig's voice, waiting in the composer. Text in a
    # column until a human reads it and presses Send — nothing sends itself.
    draft_reply: Mapped[str | None] = mapped_column(Text)

    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True, default=OPEN)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="joined")
    handler: Mapped[User | None] = relationship(foreign_keys=[handled_by], lazy="joined")
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by], lazy="joined")
    notes: Mapped[list["Note"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="Note.created_at",
    )
    replies: Mapped[list["Reply"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="Reply.sent_at",
    )
    classification_events: Mapped[list["ClassificationEvent"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="ClassificationEvent.id",
    )


class Reply(Base):
    __tablename__ = "replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    # Who actually clicked Send. The customer sees the mailbox, not this person.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    body_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # Set in Phase 2 once we actually hand the reply to Microsoft Graph.
    graph_sent_id: Mapped[str | None] = mapped_column(String(255))

    message: Mapped[Message] = relationship(back_populates="replies")
    user: Mapped[User | None] = relationship(lazy="joined")


class Note(Base):
    """An internal note on a message. Never seen by the customer.

    Two ways one appears: someone types it in the portal, or the office replies
    to each other on the customer's own email thread — which they do — and the
    poller lands it here rather than creating a second queue item.
    """

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    # Null when it came from mail sent by someone who isn't a portal user.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    author_name: Mapped[str] = mapped_column(String(255), default="")
    body_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    # Set when the note came from an email rather than the portal. Also stops
    # the same internal reply being recorded twice.
    graph_message_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True
    )

    message: Mapped[Message] = relationship(back_populates="notes")
    user: Mapped[User | None] = relationship(lazy="joined")


class MailboxState(Base):
    """Where the poller got to in each monitored mailbox.

    The delta link is the whole point: it's how a restart resumes instead of
    re-ingesting the mailbox from the beginning.
    """

    __tablename__ = "mailbox_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    mailbox: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    delta_link: Mapped[str | None] = mapped_column(Text)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last failure, kept so a mailbox that's quietly broken is visible rather
    # than just looking like a mailbox with no new mail.
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )


class ClassificationEvent(Base):
    __tablename__ = "classification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    from_queue: Mapped[str | None] = mapped_column(String(16))
    # NULL changed_by means the model made this call. A user id means a human
    # corrected it.
    to_queue: Mapped[str] = mapped_column(String(16))
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confidence: Mapped[int | None] = mapped_column(Integer)
    # One of EVENT_KINDS. Confirmations and rejections carry the same queue in
    # from_queue and to_queue — the signal is the verdict, not a move.
    kind: Mapped[str] = mapped_column(
        String(16), default=KIND_MODEL, server_default=KIND_MODEL, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    message: Mapped[Message] = relationship(back_populates="classification_events")
    changer: Mapped[User | None] = relationship(lazy="joined")


class PrivateSender(Base):
    """A sender whose mail must never appear in the portal.

    The pattern is a lowercase address, or a whole domain stored with a
    leading "@". Matching mail is skipped at ingest, and adding an entry
    purges whatever that sender already had in the queue. Every portal user
    can see and edit the list — there is no admin role yet, and a privacy
    control nobody can inspect is worse than one everybody can.
    """

    __tablename__ = "private_senders"

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    added_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    adder: Mapped[User | None] = relationship(lazy="joined")


class SessionToken(Base):
    """A logged-in browser. The cookie holds this id; nothing else."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped[User] = relationship(lazy="joined")
