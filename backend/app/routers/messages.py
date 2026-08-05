"""The queue itself: listing, assigning, moving, handling, replying.

Two rules from the brief show up throughout this file:

  Assignment doesn't own the message. Anyone can act on anything. There is no
  permission check beyond "you are signed in" — it's a five-person office.

  Handled is separate from replied. Sending a reply marks a message handled by
  default, but a message can be handled without a reply and reopened after one.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..db import get_db, utcnow
from ..graph import GraphClient, GraphError
from ..models import (
    HANDLED,
    OPEN,
    QUEUES,
    ClassificationEvent,
    Message,
    Note,
    Reply,
    User,
)
from ..schemas import (
    AssignIn,
    MessageDetailOut,
    MessageListOut,
    MessageOut,
    NoteIn,
    QueueCounts,
    QueueIn,
    ReplyIn,
    StatusIn,
)
from ..serializers import message_detail_out, message_out

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _get_message(db: Session, message_id: int) -> Message:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That message isn't in the queue anymore.",
        )
    return message


@router.get("", response_model=MessageListOut)
def list_messages(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    queue: str = Query("all", pattern="^(all|service|sales|other)$"),
    scope: str = Query("open", pattern="^(open|mine|done)$"),
) -> MessageListOut:
    q = db.query(Message)

    if queue != "all":
        q = q.filter(Message.queue == queue)

    if scope == "done":
        q = q.filter(Message.status == HANDLED)
    else:
        q = q.filter(Message.status == OPEN)
        if scope == "mine":
            q = q.filter(Message.assignee_id == user.id)

    # Emergencies first, then newest.
    rows = q.order_by(
        Message.is_urgent.desc(), Message.received_at.desc(), Message.id.desc()
    ).all()

    # Counts always describe what's still open, regardless of the current view.
    open_by_queue = {name: 0 for name in QUEUES}
    for name, count in (
        db.query(Message.queue, func.count(Message.id))
        .filter(Message.status == OPEN)
        .group_by(Message.queue)
        .all()
    ):
        if name in open_by_queue:
            open_by_queue[name] = count

    counts = QueueCounts(
        all=sum(open_by_queue.values()),
        service=open_by_queue["service"],
        sales=open_by_queue["sales"],
        other=open_by_queue["other"],
    )

    return MessageListOut(
        messages=[message_out(m) for m in rows],
        counts=counts,
    )


@router.get("/{message_id}", response_model=MessageDetailOut)
def get_message(
    message_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> MessageDetailOut:
    return message_detail_out(_get_message(db, message_id))


@router.post("/{message_id}/assign", response_model=MessageDetailOut)
def assign_message(
    message_id: int,
    payload: AssignIn,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> MessageDetailOut:
    message = _get_message(db, message_id)

    if payload.assignee_id is not None:
        assignee = db.get(User, payload.assignee_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That person isn't on the roster.",
            )

    message.assignee_id = payload.assignee_id
    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/queue", response_model=MessageDetailOut)
def move_queue(
    message_id: int,
    payload: QueueIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    message = _get_message(db, message_id)

    if payload.queue == message.queue:
        return message_detail_out(message)

    # This row is the whole point of the table: a human disagreed with the
    # model, and here is exactly how.
    db.add(
        ClassificationEvent(
            message_id=message.id,
            from_queue=message.queue,
            to_queue=payload.queue,
            changed_by=user.id,
            confidence=message.confidence,
        )
    )

    message.queue = payload.queue
    # A human said so, so there's nothing left to be unsure about.
    message.confidence = 100

    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/status", response_model=MessageDetailOut)
def set_status(
    message_id: int,
    payload: StatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    message = _get_message(db, message_id)

    if payload.status == HANDLED:
        message.status = HANDLED
        message.handled_at = utcnow()
        message.handled_by = user.id
    else:
        message.status = OPEN
        message.handled_at = None
        message.handled_by = None

    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/notes", response_model=MessageDetailOut)
def add_note(
    message_id: int,
    payload: NoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    """Leave an internal note. The customer never sees these.

    The poller writes notes here too, when the office replies to each other on
    a customer's own email thread.
    """
    message = _get_message(db, message_id)

    body = payload.body_text.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Write something before saving the note.",
        )

    db.add(
        Note(
            message_id=message.id,
            user_id=user.id,
            author_name=user.display_name,
            body_text=body,
        )
    )
    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/reply", response_model=MessageDetailOut)
def send_reply(
    message_id: int,
    payload: ReplyIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    """Send a reply from the mailbox the message arrived at.

    The customer sees that mailbox, never the person who pressed Send — a
    message to craigz@ is answered as Craig even when Joyce writes it. Who
    actually sent it is recorded here.

    Nothing sends automatically. This only ever runs because a human clicked.
    """
    message = _get_message(db, message_id)

    body = payload.body_text.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Write something before sending.",
        )

    # Hand it to Microsoft first. If that fails we want to know before the
    # message is marked handled and disappears from the queue.
    graph_sent_id: str | None = None
    if settings.graph_configured and message.graph_message_id:
        try:
            with GraphClient() as graph:
                graph.send_reply(message.mailbox, message.graph_message_id, body)
            graph_sent_id = message.graph_message_id
        except GraphError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Couldn't send through Microsoft 365, so nothing was sent "
                    "and nothing was changed. Your text is still here — try "
                    f"again in a moment. ({exc})"
                ),
            )

    db.add(
        Reply(
            message_id=message.id,
            user_id=user.id,
            body_text=body,
            sent_at=utcnow(),
            graph_sent_id=graph_sent_id,
        )
    )

    if payload.mark_handled:
        message.status = HANDLED
        message.handled_at = utcnow()
        message.handled_by = user.id

    # Whoever answers it owns it, unless someone already does.
    if message.assignee_id is None:
        message.assignee_id = user.id

    db.commit()
    db.refresh(message)
    return message_detail_out(message)
