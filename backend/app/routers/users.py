"""The office roster. Feeds the assign menu."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User
from ..schemas import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> list[UserOut]:
    users = (
        db.query(User)
        .filter(User.is_active.is_(True))
        .order_by(User.display_name)
        .all()
    )
    return [UserOut.model_validate(u) for u in users]
