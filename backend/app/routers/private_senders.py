"""The private-senders list, managed from the portal.

Anyone who can sign in can see and edit the list. That's deliberate for now:
the portal has no admin role yet, the office is four people, and a privacy
control only Brad can operate would mean private mail sits visible until a
consultant gets around to it. Revisit when SSO brings a real admin role.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import PrivateSender, User
from ..privacy import normalize_pattern, purge_matching
from ..schemas import PrivateSenderAddOut, PrivateSenderIn, PrivateSenderOut, UserOut

router = APIRouter(prefix="/api/private-senders", tags=["private-senders"])


def _out(entry: PrivateSender) -> PrivateSenderOut:
    return PrivateSenderOut(
        id=entry.id,
        pattern=entry.pattern,
        created_at=entry.created_at,
        added_by=UserOut.model_validate(entry.adder) if entry.adder else None,
    )


@router.get("", response_model=list[PrivateSenderOut])
def list_private_senders(
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[PrivateSenderOut]:
    entries = (
        db.execute(select(PrivateSender).order_by(PrivateSender.created_at.desc()))
        .scalars()
        .all()
    )
    return [_out(e) for e in entries]


@router.post(
    "", response_model=PrivateSenderAddOut, status_code=status.HTTP_201_CREATED
)
def add_private_sender(
    payload: PrivateSenderIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PrivateSenderAddOut:
    """Add an entry and purge whatever that sender already has in the queue.

    The purge is permanent for the portal; the mail itself is untouched in
    Outlook, because ingestion only ever reads.
    """
    try:
        pattern = normalize_pattern(payload.pattern)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    exists = (
        db.execute(select(PrivateSender).where(PrivateSender.pattern == pattern))
        .scalars()
        .first()
    )
    if exists:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"{pattern} is already on the list."
        )

    entry = PrivateSender(pattern=pattern, added_by=user.id)
    db.add(entry)
    purged = purge_matching(db, pattern)
    db.commit()
    db.refresh(entry)
    return PrivateSenderAddOut(entry=_out(entry), purged=purged)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_private_sender(
    entry_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> None:
    """Stop blocking a sender. Purged mail stays gone; new mail flows again."""
    entry = db.get(PrivateSender, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such entry.")
    db.delete(entry)
    db.commit()
