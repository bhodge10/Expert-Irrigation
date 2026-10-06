"""Small admin commands. Run from the backend/ directory.

    python manage.py seed                    load the five users + demo mail
    python manage.py seed --reset            wipe messages first, keep users
    python manage.py adduser                 add one office user, interactively
    python manage.py passwd EMAIL            change someone's password
    python manage.py users                   list who can sign in
    python manage.py deactivate EMAIL        stop a login, keep the history
    python manage.py events                  what the sorting called, and who
                                             corrected it
    python manage.py checkgraph              prove the Microsoft 365 connection,
                                             read-only
    python manage.py checkservicetitan       prove the ServiceTitan connection,
                                             one read per granted scope
    python manage.py lookup ID|--phone N     build the ServiceTitan card for a
                                             queued message, or for a number
    python manage.py lookup --recent         ...for whoever's job changed last
    python manage.py lookup --member         ...for someone with a membership
    python manage.py lookup --scheduled      ...for someone with a visit booked
    python manage.py classify                sort the unclassified open messages
                                             through the Claude model
    python manage.py draft                   draft replies for open service and
                                             sales messages that lack one

Migrations are Alembic's job, not this script's:  alembic upgrade head
"""

import argparse
import getpass
import sys
from datetime import timedelta

from sqlalchemy import func

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal, utcnow
from app.graph import GraphClient, GraphError
from app.models import ClassificationEvent, Message, Reply, SessionToken, User
from app.seed_data import MESSAGES, USERS
from app.servicetitan import ServiceTitanClient, ServiceTitanError

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


def cmd_checkgraph(_: argparse.Namespace) -> int:
    """Prove the Microsoft 365 connection: a token, then one read per mailbox.

    Read-only — sends nothing, tags nothing, and doesn't touch the poller's
    delta links. Run it right after finishing docs/azure-setup.md, and again
    whenever ingestion stops and you don't know why.
    """
    missing = [
        name
        for name, value in [
            ("MS_TENANT_ID", settings.ms_tenant_id),
            ("MS_CLIENT_ID", settings.ms_client_id),
            ("MS_CLIENT_SECRET", settings.ms_client_secret),
        ]
        if not value.strip()
    ]
    if missing:
        print(f"Not configured: {', '.join(missing)} empty or unset in .env.")
        print("The walkthrough is docs/azure-setup.md.")
        return 1

    mailboxes = settings.mailbox_list
    if not mailboxes:
        print("MONITORED_MAILBOXES is empty — nothing to check.")
        return 1

    with GraphClient() as graph:
        try:
            graph.check_token()
        except GraphError as exc:
            print(f"No token: {exc}")
            return 1
        print("Token acquired — the credentials are good.\n")

        failed = 0
        for mailbox in mailboxes:
            try:
                newest = graph.newest_message(mailbox)
            except GraphError as exc:
                failed += 1
                if exc.status == 403:
                    print(
                        f"  {mailbox:<30} DENIED — not in the RBAC scope, or "
                        "the permission cache hasn't caught up (up to 2 "
                        "hours). See docs/azure-setup.md, Part 5."
                    )
                elif exc.status == 404:
                    print(
                        f"  {mailbox:<30} NOT FOUND — misspelled, or no such "
                        "mailbox."
                    )
                else:
                    print(f"  {mailbox:<30} FAILED — {exc}")
                continue

            if newest is None:
                print(f"  {mailbox:<30} ok (inbox is empty)")
            else:
                subject = (newest.get("subject") or "(no subject)")[:48]
                print(f"  {mailbox:<30} ok — newest: {subject}")

    print()
    if failed:
        print(f"{failed} of {len(mailboxes)} mailbox(es) unreachable.")
        return 1
    print("All mailboxes reachable. Reading is proven; sending can only be")
    print("proven by sending — the first real reply from the portal is that test.")
    return 0


def cmd_checkservicetitan(_: argparse.Namespace) -> int:
    """Prove the ServiceTitan connection: a token, then one read per scope.

    Read-only — the app holds nothing but View scopes, so it couldn't write
    if it tried. Prints record counts, never records. Run it after finishing
    docs/servicetitan-setup.md, and whenever the lookup card goes blank.
    """
    missing = [
        name
        for name, value in [
            ("SERVICETITAN_APP_KEY", settings.servicetitan_app_key),
            ("SERVICETITAN_TENANT_ID", settings.servicetitan_tenant_id),
            ("SERVICETITAN_CLIENT_ID", settings.servicetitan_client_id),
            ("SERVICETITAN_CLIENT_SECRET", settings.servicetitan_client_secret),
        ]
        if not value.strip()
    ]
    if missing:
        print(f"Not configured: {', '.join(missing)} empty or unset in .env.")
        print("The walkthrough is docs/servicetitan-setup.md.")
        return 1

    try:
        st = ServiceTitanClient()
    except ValueError as exc:
        print(exc)
        return 1

    with st:
        try:
            st.check_token()
        except ServiceTitanError as exc:
            print(f"No token: {exc}")
            return 1
        print(
            f"Token acquired — the credentials are good "
            f"({st.environment} environment, tenant {st.tenant_id}).\n"
        )

        results = st.probe()

    failed = 0
    for result in results:
        if result.ok:
            count = (
                f"{result.total:,} record(s)" if result.total is not None else "readable"
            )
            print(f"  {result.scope:<22} ok — {count}")
        else:
            failed += 1
            print(f"  {result.scope:<22} {result.detail}")

    print()
    if failed:
        print(f"{failed} of {len(results)} scope(s) unreadable.")
        return 1
    print("All scopes readable. That is the whole grant — the app has no write")
    print("scopes, so there is nothing further to prove.")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    """Backfill: run the classifier over open messages still at 0 confidence.

    New mail classifies at ingest; this catches everything that arrived
    before the classifier existed (or while it was failing). Messages a
    human has already judged are left alone — their verdict outranks the
    model's. Commits one message at a time so an interrupted run keeps its
    progress.
    """
    if not settings.classification_configured:
        print("ANTHROPIC_API_KEY is empty — set it in .env first.")
        return 1

    from app.classify import classify_new
    from app.models import HANDLED, KIND_MODEL, OPEN

    db = SessionLocal()
    try:
        q = db.query(Message).filter(Message.status == OPEN)
        if not args.all:
            q = q.filter(Message.confidence == 0)
        candidates = q.order_by(Message.id).all()

        done = skipped = failed = 0
        for message in candidates:
            if args.limit and done + failed >= args.limit:
                break
            if any(e.changed_by is not None for e in message.classification_events):
                skipped += 1
                continue

            c = classify_new(
                db,
                mailbox=message.mailbox,
                from_name=message.from_name,
                from_email=message.from_email,
                subject=message.subject,
                body=message.body_clean or message.body_text,
            )
            if c.source == "unsorted":
                failed += 1
                print(f"#{message.id:<4} FAILED — left unsorted   {message.subject[:48]}")
                continue

            from_queue = message.queue
            message.queue = c.queue
            message.confidence = c.confidence
            message.is_urgent = c.is_urgent
            message.classification_reasons = c.reasons
            # Privacy only ever tightens in a backfill: the model flagging
            # old mail hides it, but it never un-hides what a person marked.
            if c.is_private:
                message.is_private = True
                if not message.visible_to:
                    message.visible_to = f",{message.mailbox.lower()},"
            if c.auto_handle:
                message.status = HANDLED
                message.handled_at = utcnow()

            db.add(
                ClassificationEvent(
                    message_id=message.id,
                    from_queue=from_queue,
                    to_queue=c.queue,
                    changed_by=None,
                    confidence=c.confidence,
                    kind=KIND_MODEL,
                )
            )
            db.commit()
            done += 1
            urgent = " URGENT" if c.is_urgent else ""
            handled = " (auto-handled)" if c.auto_handle else ""
            print(
                f"#{message.id:<4} -> {c.queue:<8} {c.confidence:>3}%{urgent}"
                f"{handled}  [{c.source}]  {message.subject[:44]}"
            )

        print(
            f"\n{done} classified, {failed} failed, {skipped} already judged "
            f"by a human, {len(candidates) - done - failed - skipped} not reached."
        )
        return 1 if failed and not done else 0
    finally:
        db.close()


def cmd_draft(args: argparse.Namespace) -> int:
    """Backfill: draft replies for open service/sales mail without one.

    New service and sales mail drafts at ingest; this catches what arrived
    before drafting existed. Commits per message, so it's safe to interrupt.
    """
    if not settings.classification_configured:
        print("ANTHROPIC_API_KEY is empty — set it in .env first.")
        return 1

    from app.draft import draft_reply_text
    from app.models import OPEN
    from app.privacy import load_patterns

    db = SessionLocal()
    graph = GraphClient() if settings.graph_configured else None
    try:
        private_patterns = load_patterns(db)
        candidates = (
            db.query(Message)
            .filter(
                Message.status == OPEN,
                Message.queue.in_(("service", "sales")),
                Message.draft_reply.is_(None),
                # Private mail is never drafted unasked — same rule as ingest.
                Message.is_private.is_(False),
            )
            .order_by(Message.id)
            .all()
        )
        if not candidates:
            print("Nothing to draft — every open service/sales message has one.")
            return 0

        done = failed = 0
        for message in candidates:
            if args.limit and done + failed >= args.limit:
                break
            text = draft_reply_text(
                graph,
                from_name=message.from_name,
                from_email=message.from_email,
                subject=message.subject,
                body=message.body_clean or message.body_text,
                mailbox=message.mailbox,
                private_senders=private_patterns,
            )
            if text is None:
                failed += 1
                print(f"#{message.id:<4} FAILED   {message.subject[:52]}")
                continue
            message.draft_reply = text
            db.commit()
            done += 1
            print(f"#{message.id:<4} drafted  {message.subject[:52]}")

        print(f"\n{done} drafted, {failed} failed.")
        return 1 if failed and not done else 0
    finally:
        if graph is not None:
            graph.close()
        db.close()


def _who_for_customer(st: ServiceTitanClient, customer_id: int) -> dict | None:
    """What an email from this customer would carry — their name, their
    address and a number in the body — so build_card can match them the
    way it matches real mail. None if the account has neither on file."""
    from app.servicetitan import normalize_phone

    record = st.customer(customer_id)
    phone = email = ""
    for contact in st.customer_contacts(customer_id):
        kind, value = contact.get("type"), contact.get("value") or ""
        if kind in ("Phone", "MobilePhone") and not phone:
            phone = normalize_phone(value) or ""
        elif kind == "Email" and not email:
            email = value
    if not phone and not email:
        return None
    return dict(from_name=record.get("name") or "", from_email=email, body=phone)


def cmd_lookup(args: argparse.Namespace) -> int:
    """Build a ServiceTitan card and print it — for checking the matching
    against real data without opening the portal. Nothing is cached.
    """
    if not settings.servicetitan_configured:
        print("ServiceTitan isn't configured — see docs/servicetitan-setup.md.")
        return 1
    if not (args.message_id or args.phone or args.recent or args.member or args.scheduled):
        print("Give a message id, --phone NUMBER, --recent, --member or --scheduled.", file=sys.stderr)
        return 1

    from app.lookup import build_card

    who: dict | None = None
    if args.message_id:
        db = SessionLocal()
        try:
            message = db.get(Message, args.message_id)
            if message is None:
                print(f"No message #{args.message_id}.", file=sys.stderr)
                return 1
            who = dict(
                from_name=message.from_name,
                from_email=message.from_email,
                body=message.body_text or "",
            )
            print(f"#{message.id}  {message.from_name} <{message.from_email}>  {message.subject[:48]}")
        finally:
            db.close()
    elif args.phone:
        who = dict(from_name="", from_email="", body=args.phone)
        print(f"Phone {args.phone}")

    with ServiceTitanClient() as st:
        try:
            if who is None:
                # --recent / --member / --scheduled: find a real customer to
                # test on, then look them up the way the portal would — by a
                # number off their account, or by name with their email.
                if args.member:
                    label = "an active membership"
                    customer_ids = [m["customerId"] for m in st.recent_memberships(limit=10)]
                elif args.scheduled:
                    label = "a visit booked"
                    customer_ids = [
                        j["customerId"] for j in st.recent_jobs(limit=10, status="Scheduled")
                    ]
                else:
                    label = "a recently changed job"
                    customer_ids = [j["customerId"] for j in st.recent_jobs(limit=10)]
                for customer_id in customer_ids:
                    who = _who_for_customer(st, customer_id)
                    if who:
                        print(f"Customer #{customer_id}, picked for having {label}")
                        break
                if who is None:
                    print(f"Couldn't find a customer with {label} and a phone or email on file.")
                    return 1
            card = build_card(st, **who)
        except ServiceTitanError as exc:
            print(f"Lookup failed: {exc}")
            return 1

    if card.status != "matched":
        print(f"{card.status} — {card.phones_tried} phone number(s) tried.")
        return 0

    c = card.customer
    how = f"phone {card.matched_phone}" if card.matched_by == "phone" else "name + email"
    print(f"matched on {how}")
    print(f"  {c.name}  [{c.type or '?'}{', inactive' if not c.active else ''}{', DO NOT SERVICE' if c.do_not_service else ''}]")
    if c.address:
        print(f"  {c.address}")
    for contact in c.contacts:
        print(f"  {contact.type:<12} {contact.value}")
    for m in card.memberships:
        print(f"  membership   {m.type} — {m.status}")
    for j in card.open_jobs:
        # UTC on purpose: the shell this runs in has no idea where the office
        # is. The portal shows the same visit in the viewer's local time.
        when = f"  next {j.next_appointment:%b %d %H:%M} UTC" if j.next_appointment else ""
        print(f"  open job     #{j.number} {j.type} — {j.status}{when}  {j.summary[:40]}")
    for j in card.recent_jobs:
        done = f" ({j.completed_on:%b %d %Y})" if j.completed_on else ""
        print(f"  recent job   #{j.number} {j.type}{done}")
    for other in card.other_matches:
        print(f"  also matches {other.name}  {other.address}")
    return 0


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

    p_cg = sub.add_parser(
        "checkgraph", help="prove the Microsoft 365 connection, read-only"
    )
    p_cg.set_defaults(func=cmd_checkgraph)

    p_cs = sub.add_parser(
        "checkservicetitan", help="prove the ServiceTitan connection, read-only"
    )
    p_cs.set_defaults(func=cmd_checkservicetitan)

    p_lk = sub.add_parser(
        "lookup", help="build the ServiceTitan card for a message or a phone number"
    )
    p_lk.add_argument("message_id", type=int, nargs="?", default=0)
    p_lk.add_argument("--phone", default="")
    p_lk.add_argument(
        "--recent",
        action="store_true",
        help="pick the customer behind the most recently changed job",
    )
    p_lk.add_argument(
        "--member", action="store_true", help="pick a customer with an active membership"
    )
    p_lk.add_argument(
        "--scheduled", action="store_true", help="pick a customer with a visit booked"
    )
    p_lk.set_defaults(func=cmd_lookup)

    p_cl = sub.add_parser(
        "classify", help="sort unclassified open messages with the Claude model"
    )
    p_cl.add_argument(
        "--limit", type=int, default=0, help="stop after this many (0 = all)"
    )
    p_cl.add_argument(
        "--all",
        action="store_true",
        help="re-sort already-classified open messages too (humans' verdicts "
        "are still never overridden)",
    )
    p_cl.set_defaults(func=cmd_classify)

    p_dr = sub.add_parser(
        "draft", help="draft replies for open service/sales messages without one"
    )
    p_dr.add_argument(
        "--limit", type=int, default=0, help="stop after this many (0 = all)"
    )
    p_dr.set_defaults(func=cmd_draft)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
