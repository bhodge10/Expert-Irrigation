"""Request and response shapes for the API."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from .models import QUEUES, STATUSES


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    initials: str
    color: str
    role: str

    model_config = {"from_attributes": True}


class LoginIn(BaseModel):
    email: EmailStr
    # bcrypt refuses anything past 72 bytes, so cap it here rather than
    # silently truncating later.
    password: str = Field(min_length=1, max_length=72)


class ReplyOut(BaseModel):
    id: int
    body_text: str
    sent_at: datetime
    sent_by: UserOut | None = None
    # False when the reply was recorded but never left the building — either
    # Graph isn't configured, or sending failed.
    delivered: bool = False


class NoteOut(BaseModel):
    """Internal note. Never seen by the customer."""

    id: int
    body_text: str
    created_at: datetime
    author_name: str
    author: UserOut | None = None
    # True when it arrived as email rather than being typed in the portal.
    from_email: bool = False


class NoteIn(BaseModel):
    body_text: str = Field(min_length=1)


class MessageOut(BaseModel):
    """List row. Everything the card needs, no HTML body."""

    id: int
    mailbox: str
    source: str = "graph"
    form_type: str | None = None
    attachment_count: int = 0
    attachment_names: list[str] = []
    from_name: str
    from_email: str
    subject: str
    body_text: str
    received_at: datetime
    queue: str
    confidence: int
    is_urgent: bool
    # Visible only to the people the email was addressed to. The server
    # filters; this flag just lets the UI say so.
    is_private: bool = False
    classification_reasons: list[str]
    assignee: UserOut | None = None
    status: str
    handled_at: datetime | None = None
    handled_by_user: UserOut | None = None


class MessageDetailOut(MessageOut):
    """Detail pane. Adds the HTML body, the reply history, and — when a human
    has overruled the sorting — who did it and what the model had picked."""

    body_html: str | None = None
    conversation_id: str | None = None
    replies: list[ReplyOut] = []
    notes: list[NoteOut] = []

    # Set only when the message no longer sits in the queue the model chose.
    original_queue: str | None = None
    corrected_by: UserOut | None = None

    # Set when someone pressed "shouldn't be here" — the message was cleared
    # from the queue and the sorting told so.
    rejected_by: UserOut | None = None

    # An AI-drafted reply waiting in the composer. Never sent by machinery.
    draft_reply: str | None = None


class PrivateSenderOut(BaseModel):
    id: int
    # An address, or a whole domain with a leading "@".
    pattern: str
    created_at: datetime
    added_by: UserOut | None = None


class PrivateSenderIn(BaseModel):
    pattern: str = Field(min_length=3, max_length=255)


class PrivateSenderAddOut(BaseModel):
    entry: PrivateSenderOut
    # How many already-ingested messages the new entry removed.
    purged: int


class QueueCounts(BaseModel):
    # "all" excludes ignored — that bucket exists to stay out of the way.
    all: int
    service: int
    sales: int
    undetermined: int
    ignored: int


class MessageListOut(BaseModel):
    messages: list[MessageOut]
    counts: QueueCounts


class AssignIn(BaseModel):
    # None clears the assignment.
    assignee_id: int | None = None


class QueueIn(BaseModel):
    queue: str = Field(pattern="^(" + "|".join(QUEUES) + ")$")


class StatusIn(BaseModel):
    status: str = Field(pattern="^(" + "|".join(STATUSES) + ")$")


class PrivateFlagIn(BaseModel):
    # True hides the message from everyone it wasn't addressed to; False
    # releases one the sorting (or a person) flagged.
    is_private: bool


class ReplyIn(BaseModel):
    body_text: str = Field(min_length=1)
    # Sending a reply marks the message handled by default. A user can turn
    # that off if the conversation is still open.
    mark_handled: bool = True
