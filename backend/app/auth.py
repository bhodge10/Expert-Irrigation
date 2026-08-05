"""Password hashing and server-side login sessions.

The browser gets one cookie holding a random session id plus a signature.
Everything else about the session lives in the database, so logging someone
out is a DELETE and nothing more.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from .config import settings
from .db import as_utc, get_db, utcnow
from .models import SessionToken, User

COOKIE_NAME = "eq_session"


def hash_password(plain: str) -> str:
    # bcrypt refuses anything past 72 bytes. Say so plainly instead of letting
    # it blow up somewhere less obvious.
    encoded = plain.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("Password must be 72 bytes or fewer.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database — treat as a failed login, not a 500.
        return False


def _sign(session_id: str) -> str:
    mac = hmac.new(
        settings.session_secret.encode("utf-8"),
        session_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{session_id}.{mac}"


def _unsign(cookie_value: str) -> str | None:
    session_id, _, mac = cookie_value.partition(".")
    if not session_id or not mac:
        return None
    expected = hmac.new(
        settings.session_secret.encode("utf-8"),
        session_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return session_id if hmac.compare_digest(mac, expected) else None


def start_session(db: Session, response: Response, user: User) -> SessionToken:
    token = SessionToken(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=utcnow() + timedelta(days=settings.session_days),
    )
    db.add(token)
    db.commit()

    response.set_cookie(
        COOKIE_NAME,
        _sign(token.id),
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return token


def end_session(db: Session, request: Request, response: Response) -> None:
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        session_id = _unsign(raw)
        if session_id:
            db.query(SessionToken).filter(SessionToken.id == session_id).delete()
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Dependency for every endpoint behind the login."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not signed in.",
    )

    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise unauthorized

    session_id = _unsign(raw)
    if not session_id:
        raise unauthorized

    token = db.get(SessionToken, session_id)
    if token is None:
        raise unauthorized

    expires_at = as_utc(token.expires_at)
    if expires_at is None or expires_at < utcnow():
        db.delete(token)
        db.commit()
        raise unauthorized

    if not token.user or not token.user.is_active:
        raise unauthorized

    return token.user
