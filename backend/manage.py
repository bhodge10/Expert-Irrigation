"""Small admin commands. Run from the backend/ directory.

    python manage.py seed                    load the five users + demo mail
    python manage.py seed --reset            wipe messages first, keep users
    python manage.py adduser                 add one office user, interactively
    python manage.py passwd EMAIL            change someone's password
    python manage.py users                   list who can sign in
    python manage.py deactivate EMAIL        stop a login, keep the history
    python manage.py events                  what the sorting called, and who
                                             corrected it

Migrations are Alembic's job, not this script's:  alembic upgrade head
"""

import argparse
import getpass
import sys
from datetime import timedelta

from sqlalchemy import func

from app.auth import hash_password
from app.db import SessionLocal, utcnow
from app.models import ClassificationEvent, Message, Reply, SessionToken, User
from app.seed_data import MESSAGES, USERS

DEFAULT_SEED_PASSWORD = "expert-dev"


def cmd_seed(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        if args.reset:
            db.query(Reply).delete()
            db.query(ClassificationEvent).delete()
            db.query(Message).delete()
            db.commit()
            print("Cleared existing messages.")

        # Users: create the missing ones, leave existing ones (and their
        # passwords) alone.
        by_key: dict[str, User] = {}
        created_users = 0
        for key, (email, name, initials, color, role) in USERS.items():
            user = (
                db.query(User)
                .filter(func.lower(User.email) == email.lower())
                .one_or_none()
            )
            if user is None:
                user = User(
                    email=email,
                    display_name=name,
                    initials=initials,
                    color=color,
                    role=role,
                    password_hash=hash_password(args.password),
                    is_active=True,
                )
                db.add(user)
                created_users += 1
            by_key[key] = user
        db.commit()

        if db.query(Message).count() > 0:
            print("Messages already present — skipping. Use --reset to reload them.")
        else:
            now = utcnow()
            for row in MESSAGES:
                assignee = by_key.get(row["assignee"]) if row["assignee"] else None
                message = Message(
                    mailbox=row["mailbox"],
                    from_name=row["from_name"],
                    from_email=row["from_email"],
                    subject=row["subject"],
                    body_text=row["body_text"],
                    received_at=now - timedelta(minutes=row["minutes_ago"]),
                    queue=row["queue"],
                    confidence=row["confidence"],
                    is_urgent=row["is_urgent"],
                    classification_reasons=row["classification_reasons"],
                    assignee_id=assignee.id if assignee else None,
                    status="open",
                )
                db.add(message)
                db.flush()  # need message.id for the event below

                # Every automatic classification gets logged, same as it will
                # in Phase 3. changed_by is NULL because the model made the call.
                db.add(
                    ClassificationEvent(
                        message_id=message.id,
                        from_queue=None,
                        to_queue=row["queue"],
                        changed_by=None,
                        confidence=row["confidence"],
                    )
                )
            db.commit()
            print(f"Loaded {len(MESSAGES)} messages.")

        if created_users:
            print(f"Created {created_users} user(s) with password: {args.password}")
            print("Change it before anyone real uses this.")
        else:
            print("Users already existed — passwords left as they are.")
        return 0
    finally:
        db.close()


def cmd_adduser(args: argparse.Namespace) -> int:
    email = (args.email or input("Email: ")).strip().lower()
    if not email:
        print("Email is required.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if (
            db.query(User)
            .filter(func.lower(User.email) == email)
            .one_or_none()
            is not None
        ):
            print(f"{email} already exists. Use 'passwd' to reset the password.")
            return 1

        display_name = (args.name or input("Display name: ")).strip()
        initials = (
            args.initials or input("Initials (1-3 letters, shown in the avatar): ")
        ).strip().upper()
        color = (
            args.color or input("Avatar color hex [#1F7A47]: ")
        ).strip() or "#1F7A47"
        role = (args.role or input("Role (e.g. Office, Sales / estimating): ")).strip()
        password = args.password or getpass.getpass("Password: ")

        if not display_name or not initials or not password:
            print("Display name, initials and password are all required.", file=sys.stderr)
            return 1

        db.add(
            User(
                email=email,
                display_name=display_name,
                initials=initials[:3],
                color=color,
                role=role or "Office",
                password_hash=hash_password(password),
                is_active=True,
            )
        )
        db.commit()
        print(f"Added {display_name} <{email}>.")
        return 0
    finally:
        db.close()


def cmd_passwd(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(func.lower(User.email) == args.email.strip().lower())
            .one_or_none()
        )
        if user is None:
            print(f"No user with email {args.email}.", file=sys.stderr)
            return 1

        password = args.password or getpass.getpass("New password: ")
        if not password:
            print("Password can't be empty.", file=sys.stderr)
            return 1

        user.password_hash = hash_password(password)
        db.commit()
        print(f"Password updated for {user.display_name}.")
        return 0
    finally:
        db.close()


def cmd_deactivate(args: argparse.Namespace) -> int:
    """Take someone out of circulation without erasing their history.

    Deleting the row would blank their name off every message they handled and
    every reply they sent. Deactivating keeps the record and stops the login.
    """
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(func.lower(User.email) == args.email.strip().lower())
            .one_or_none()
        )
        if user is None:
            print(f"No user with email {args.email}.", file=sys.stderr)
            return 1

        user.is_active = args.reactivate
        # Signing out anyone currently using that account.
        if not args.reactivate:
            db.query(SessionToken).filter(SessionToken.user_id == user.id).delete()
        db.commit()

        state = "reactivated" if args.reactivate else "deactivated"
        print(f"{user.display_name} {state}.")
        return 0
    finally:
        db.close()


def cmd_events(args: argparse.Namespace) -> int:
    """Print the classification trail — what the sorting called, what humans
    corrected. This is the raw material for tuning the Phase 3 prompt."""
    db = SessionLocal()
    try:
        q = db.query(ClassificationEvent).order_by(ClassificationEvent.id)
        if args.corrections_only:
            q = q.filter(ClassificationEvent.changed_by.isnot(None))

        rows = q.all()
        if not rows:
            print("No classification events yet.")
            return 0

        for event in rows:
            who = "model"
            if event.changed_by:
                changer = db.get(User, event.changed_by)
                who = changer.display_name if changer else f"user {event.changed_by}"
            origin = event.from_queue or "(new)"
            message = db.get(Message, event.message_id)
            subject = (message.subject[:48] + "…") if message else "(deleted)"
            print(
                f"#{event.message_id:<4} {origin:>8} -> {event.to_queue:<8} "
                f"by {who:<16} at {event.confidence}%   {subject}"
            )

        corrections = sum(1 for e in rows if e.changed_by is not None)
        print(f"\n{len(rows)} event(s), {corrections} human correction(s).")
        return 0
    finally:
        db.close()


def cmd_users(_: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        rows = db.query(User).order_by(User.display_name).all()
        if not rows:
            print("No users yet. Run: python manage.py seed")
            return 0
        for u in rows:
            state = "" if u.is_active else "  (inactive)"
            print(f"{u.display_name:<20} {u.email:<28} {u.role}{state}")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="load demo users and messages")
    p_seed.add_argument(
        "--reset", action="store_true", help="delete existing messages first"
    )
    p_seed.add_argument(
        "--password",
        default=DEFAULT_SEED_PASSWORD,
        help=f"password for newly created users (default: {DEFAULT_SEED_PASSWORD})",
    )
    p_seed.set_defaults(func=cmd_seed)

    p_add = sub.add_parser("adduser", help="add one office user")
    for flag in ("email", "name", "initials", "color", "role", "password"):
        p_add.add_argument(f"--{flag}")
    p_add.set_defaults(func=cmd_adduser)

    p_pw = sub.add_parser("passwd", help="change a password")
    p_pw.add_argument("email")
    p_pw.add_argument("--password")
    p_pw.set_defaults(func=cmd_passwd)

    p_off = sub.add_parser(
        "deactivate", help="stop someone signing in, keeping their history"
    )
    p_off.add_argument("email")
    p_off.add_argument(
        "--reactivate", action="store_true", help="turn the account back on"
    )
    p_off.set_defaults(func=cmd_deactivate)

    p_ev = sub.add_parser("events", help="show the classification trail")
    p_ev.add_argument(
        "--corrections-only",
        action="store_true",
        help="only the times a human overruled the sorting",
    )
    p_ev.set_defaults(func=cmd_events)

    p_ls = sub.add_parser("users", help="list users")
    p_ls.set_defaults(func=cmd_users)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
