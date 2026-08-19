"""The private-senders list: mail that must never appear in the portal.

The portal is a shared surface — every login sees every queue, Ignored
included. That's right for customer mail and wrong for, say, the payroll
company writing to Craig and Megan. An entry here is an address
("kturner@midwestpaylink.com") or a whole domain (stored with a leading "@",
"@midwestpaylink.com"), and mail matching one is skipped at ingest before
anything is stored.

Adding an entry also purges whatever that sender already has in the queue —
privacy that starts from the first email, not from today. The purge deletes
the queue items outright (notes, replies and classification events go with
them); the mail itself is untouched in Outlook, because ingestion only ever
reads.

The matching convention lives in two places that must agree:
`app.mail.rules.is_private` (pure, used at ingest) and `purge_matching`
here (SQL). Both are pinned by tests/test_private_senders.py.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Message, PrivateSender


def normalize_pattern(raw: str) -> str:
    """Turn what a person typed into a stored pattern, or raise ValueError.

    "KTurner@Midwestpaylink.com"  -> "kturner@midwestpaylink.com"
    "midwestpaylink.com"          -> "@midwestpaylink.com"  (whole domain)
    "@midwestpaylink.com"         -> "@midwestpaylink.com"
    """
    value = (raw or "").strip().lower().rstrip(",;")
    if value.startswith("mailto:"):
        value = value[len("mailto:"):]
    problem = ValueError(
        f'"{(raw or "").strip()}" doesn\'t look like an email address '
        f'or a domain like "midwestpaylink.com".'
    )
    if not value or " " in value:
        raise problem

    # No "@" means they typed a bare domain and mean all of it.
    if "@" not in value:
        value = "@" + value

    local, _, domain = value.rpartition("@")
    if "@" in local or "." not in domain:
        raise problem
    if domain.startswith(".") or domain.endswith("."):
        raise problem
    return value


def load_patterns(db: Session) -> list[str]:
    """Every stored pattern, for the ingest decision."""
    return list(db.execute(select(PrivateSender.pattern)).scalars())


def purge_matching(db: Session, pattern: str) -> int:
    """Delete every queue item from a sender matching `pattern`.

    Deletes through the ORM so notes, replies and classification events
    cascade with their message. Returns how many items went.
    """
    if pattern.startswith("@"):
        # LIKE narrows the scan; endswith is the exact check, because "_" is
        # a LIKE wildcard and "@paylink.com" must not catch midwestpaylink.
        candidates = (
            db.execute(
                select(Message).where(
                    func.lower(Message.from_email).like(f"%{pattern}")
                )
            )
            .scalars()
            .all()
        )
        doomed = [m for m in candidates if m.from_email.lower().endswith(pattern)]
    else:
        doomed = (
            db.execute(
                select(Message).where(func.lower(Message.from_email) == pattern)
            )
            .scalars()
            .all()
        )

    for message in doomed:
        db.delete(message)
    return len(doomed)
