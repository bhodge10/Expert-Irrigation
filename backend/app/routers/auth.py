"""Sign in, sign out, and who-am-I."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user, end_session, start_session, verify_password
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(
    payload: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
) -> UserOut:
    email = payload.email.strip().lower()
    user = (
        db.query(User)
        .filter(func.lower(User.email) == email, User.is_active.is_(True))
        .one_or_none()
    )

    # Same message either way — don't tell a stranger which emails exist.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That email and password don't match. Try again.",
        )

    start_session(db, response, user)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> None:
    end_session(db, request, response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)
