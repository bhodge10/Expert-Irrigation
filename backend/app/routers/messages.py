"""The queue itself: listing, assigning, moving, handling, replying.

Two rules from the brief show up throughout this file:

  Assignment doesn't own the message. Anyone can act on anything. There is no
  permission check beyond "you are signed in" — it's a five-person office.

  Handled is separate from replied. Sending a reply marks a message handled by
  default, but a message can be handled without a reply and reopened after one.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..db import get_db, utcnow
from ..graph import GraphClient, GraphError
from ..models import (
    HANDLED,
    IGNORED,
    KIND_CONFIRMATION,
    KIND_CORRECTION,
    KIND_REJECTION,
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
    PrivateFlagIn,
    QueueCounts,
    QueueIn,
    ReplyIn,
    StatusIn,
)
from ..serializers import message_detail_out, message_out

router = APIRouter(prefix="/api/messages", tags=["messages"])


def _can_see(message: Message, user: User) -> bool:
    """Private mail is for the people it was addressed to, nobody else."""
    if not message.is_private:
        return True
    return f",{user.email.lower()}," in (message.visible_to or "")


def _visibility_filter(user: User):
    """The same rule as _can_see, for list and count queries."""
    return or_(
        Message.is_private.is_(False),
        Message.visible_to.like(f"%,{user.email.lower()},%"),
    )


def _get_message(db: Session, message_id: int, user: User) -> Message:
    message = db.get(Message, message_id)
    # A private message someone can't see 404s rather than 403s — "it isn't
    # here" reveals nothing, "you can't have it" confirms it exists.
    if message is None or not _can_see(message, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That message isn't in the queue anymore.",
        )
    return message


def _confirm_sorting(db: Session, message: Message, user: User) -> None:
    """Record that a human worked this message where the sorting put it.

    Assigning, marking handled, and replying all say the same thing: this was
    a real request, in the right queue. One confirmation per message is
    enough, and any earlier human verdict — a correction or a rejection —
    outranks it, so this stays silent if one exists.
    """
    if any(e.changed_by is not None for e in message.classification_events):
        return
    db.add(
        ClassificationEvent(
            message_id=message.id,
            from_queue=message.queue,
            to_queue=message.queue,
            changed_by=user.id,
            confidence=message.confidence,
            kind=KIND_CONFIRMATION,
        )
    )


@router.get("", response_model=MessageListOut)
def list_messages(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    queue: str = Query("all", pattern="^(all|service|sales|undetermined|ignored)$"),
    scope: str = Query("open", pattern="^(open|mine|done)$"),
) -> MessageListOut:
    q = db.query(Message).filter(_visibility_filter(user))

    if queue == "all":
        # "All" means all the mail worth a look — Ignored stays in its own
        # bucket, which is the whole point of having it.
        q = q.filter(Message.queue != IGNORED)
    else:
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
        .filter(Message.status == OPEN, _visibility_filter(user))
        .group_by(Message.queue)
        .all()
    ):
        if name in open_by_queue:
            open_by_queue[name] = count

    counts = QueueCounts(
        # "all" is the actionable open mail; Ignored is counted separately.
        all=sum(n for name, n in open_by_queue.items() if name != IGNORED),
        service=open_by_queue["service"],
        sales=open_by_queue["sales"],
        undetermined=open_by_queue["undetermined"],
        ignored=open_by_queue["ignored"],
    )

    return MessageListOut(
        messages=[message_out(m) for m in rows],
        counts=counts,
    )


@router.get("/{message_id}", response_model=MessageDetailOut)
def get_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    return message_detail_out(_get_message(db, message_id, user))


@router.post("/{message_id}/private", response_model=MessageDetailOut)
def set_private(
    message_id: int,
    payload: PrivateFlagIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    """Flag a message private, or release one the sorting flagged.

    Only someone who can already see the message gets here. Marking it
    private keeps the marker in the audience — hiding mail from yourself
    is never what anyone means — alongside whoever it was addressed to.
    """
    message = _get_message(db, message_id, user)

    if payload.is_private:
        # Older rows predate visible_to, so rebuild the audience from what's
        # known: whoever was already in it, the mailbox owner, the marker.
        audience = {e for e in (message.visible_to or "").split(",") if e}
        audience.add(message.mailbox.lower())
        audience.add(user.email.lower())
        message.visible_to = "," + ",".join(sorted(audience)) + ","
    message.is_private = payload.is_private

    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/assign", response_model=MessageDetailOut)
def assign_message(
    message_id: int,
    payload: AssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    message = _get_message(db, message_id, user)

    if payload.assignee_id is not None:
        assignee = db.get(User, payload.assignee_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That person isn't on the roster.",
            )

    message.assignee_id = payload.assignee_id
    # Giving it to someone says the request is real and sorted right. Clearing
    # an assignment says nothing.
    if payload.assignee_id is not None:
        _confirm_sorting(db, message, user)
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
    message = _get_message(db, message_id, user)

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
            kind=KIND_CORRECTION,
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
    message = _get_message(db, message_id, user)

    if payload.status == HANDLED:
        message.status = HANDLED
        message.handled_at = utcnow()
        message.handled_by = user.id
        # Handling it where it landed is the quiet "the sorting was right".
        _confirm_sorting(db, message, user)
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
    message = _get_message(db, message_id, user)

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
    message = _get_message(db, message_id, user)

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

    # Nobody replies to a misfiled message — answering it confirms the sort.
    _confirm_sorting(db, message, user)

    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/draft", response_model=MessageDetailOut)
def draft_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    """Generate (or regenerate) an AI draft for the composer, on demand.

    Service and sales mail gets drafted at ingest; this covers everything
    else — an Other-queue message that turns out to deserve an answer, or a
    draft someone wants a second take on. Nothing sends: the draft sits in
    the composer until a human presses Send.
    """
    if not settings.classification_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Drafting is off — ANTHROPIC_API_KEY isn't configured.",
        )

    message = _get_message(db, message_id, user)

    from ..draft import draft_reply_text
    from ..privacy import load_patterns

    patterns = load_patterns(db)
    if settings.graph_configured:
        with GraphClient() as graph:
            text = draft_reply_text(
                graph,
                from_name=message.from_name,
                from_email=message.from_email,
                subject=message.subject,
                body=message.body_clean or message.body_text,
                mailbox=message.mailbox,
                private_senders=patterns,
            )
    else:
        text = draft_reply_text(
            None,
            from_name=message.from_name,
            from_email=message.from_email,
            subject=message.subject,
            body=message.body_clean or message.body_text,
            mailbox=message.mailbox,
            private_senders=patterns,
        )

    if text is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Couldn't draft a reply just now — try again in a moment.",
        )

    message.draft_reply = text
    db.commit()
    db.refresh(message)
    return message_detail_out(message)


@router.post("/{message_id}/reject", response_model=MessageDetailOut)
def reject_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> MessageDetailOut:
    """The "shouldn't be here" button: spam, vendor noise, a misfire.

    Records the strongest negative signal the sorting can get, then clears
    the message from the open queue. Nothing is deleted — the row and its
    verdict are exactly what the classifier learns from later, and Reopen
    undoes the clearing if the button was pressed by mistake.
    """
    message = _get_message(db, message_id, user)

    if not any(e.kind == KIND_REJECTION for e in message.classification_events):
        db.add(
            ClassificationEvent(
                message_id=message.id,
                from_queue=message.queue,
                to_queue=IGNORED,
                changed_by=user.id,
                confidence=message.confidence,
                kind=KIND_REJECTION,
            )
        )

    message.queue = IGNORED
    message.status = HANDLED
    message.handled_at = utcnow()
    message.handled_by = user.id

    db.commit()
    db.refresh(message)
    return message_detail_out(message)
