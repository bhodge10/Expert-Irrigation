"""Turning ORM rows into API responses.

Kept in one place so the list and detail views can never drift apart.
"""

from .db import as_utc
from .models import KIND_CORRECTION, KIND_REJECTION, Message, Note, Reply, User
from .schemas import MessageDetailOut, MessageOut, NoteOut, ReplyOut, UserOut


def user_out(user: User | None) -> UserOut | None:
    if user is None:
        return None
    return UserOut.model_validate(user)


def reply_out(reply: Reply) -> ReplyOut:
    return ReplyOut(
        id=reply.id,
        body_text=reply.body_text,
        sent_at=as_utc(reply.sent_at),
        sent_by=user_out(reply.user),
        # A graph_sent_id means Microsoft accepted it. Without one it's on
        # record here and nowhere else, and the customer never saw it.
        delivered=bool(reply.graph_sent_id),
    )


def note_out(note: Note) -> NoteOut:
    return NoteOut(
        id=note.id,
        body_text=note.body_text,
        created_at=as_utc(note.created_at),
        author_name=note.author_name or (note.user.display_name if note.user else ""),
        author=user_out(note.user),
        from_email=bool(note.graph_message_id),
    )


def _base_fields(message: Message) -> dict:
    return {
        "id": message.id,
        "mailbox": message.mailbox,
        "from_name": message.from_name,
        "from_email": message.from_email,
        "subject": message.subject,
        "body_text": message.body_text or "",
        "received_at": as_utc(message.received_at),
        "queue": message.queue,
        "confidence": message.confidence,
        "is_urgent": message.is_urgent,
        "is_private": message.is_private,
        "classification_reasons": message.classification_reasons or [],
        "assignee": user_out(message.assignee),
        "status": message.status,
        "handled_at": as_utc(message.handled_at),
        "handled_by_user": user_out(message.handler),
        "source": message.source,
        "form_type": message.form_type,
        "attachment_count": message.attachment_count,
        "attachment_names": message.attachment_names or [],
    }


def message_out(message: Message) -> MessageOut:
    return MessageOut(**_base_fields(message))


def message_detail_out(message: Message) -> MessageDetailOut:
    """Detail view, plus enough history to caption the reasons honestly.

    Once a human has moved a message, the stored reasons are the model's
    reasons for a queue nobody is looking at anymore. The detail pane needs to
    know that so it can say so rather than presenting them as current.
    """
    events = message.classification_events
    corrections = [e for e in events if e.kind == KIND_CORRECTION]
    rejections = [e for e in events if e.kind == KIND_REJECTION]

    original_queue = events[0].to_queue if events else None
    corrected_by = user_out(corrections[-1].changer) if corrections else None

    return MessageDetailOut(
        **_base_fields(message),
        body_html=message.body_html,
        conversation_id=message.conversation_id,
        replies=[reply_out(r) for r in message.replies],
        notes=[note_out(n) for n in message.notes],
        original_queue=original_queue if original_queue != message.queue else None,
        corrected_by=corrected_by,
        rejected_by=user_out(rejections[-1].changer) if rejections else None,
        draft_reply=message.draft_reply,
    )
