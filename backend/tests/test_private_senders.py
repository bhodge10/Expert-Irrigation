"""The private-senders list: mail that must never appear in the portal.

Born from a real one: the payroll company wrote to Craig and Megan, the
sorter filed it in Ignored, and there it sat — readable by every login.
Blocking is two mechanisms that must agree: the ingest skip
(app.mail.rules.is_private) and the purge of what's already in
(app.privacy.purge_matching). Both are pinned here.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.db import Base, get_db, utcnow
from app.ingest import ingest_one
from app.main import app
from app.mail.rules import Action, decide, is_private
from app.models import Message, Note, PrivateSender, Reply, User
from app.privacy import normalize_pattern, purge_matching

from . import fixtures as fx
from .test_ingest_rules import INTERNAL, MAILBOXES, WEBSITE_SENDERS, graph_message, norm

PAYROLL = "kturner@midwestpaylink.com"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def craig(db):
    user = User(
        email="craigz@expertsvc.com",
        display_name="Craig Zumdick",
        initials="C",
        color="#1F7A47",
        role="Owner",
        password_hash="x",
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def client(db, craig):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: craig
    yield TestClient(app)
    app.dependency_overrides.clear()


def queued(db, from_email, from_name="Keith Turner", subject="(private)"):
    msg = Message(
        mailbox="craigz@expertsvc.com",
        from_name=from_name,
        from_email=from_email,
        subject=subject,
        body_text="…",
        received_at=utcnow(),
        queue="ignored",
        confidence=95,
    )
    db.add(msg)
    db.commit()
    return msg


# --- the pattern language -------------------------------------------------

def test_addresses_and_domains_normalise():
    assert normalize_pattern(" KTurner@Midwestpaylink.com ") == PAYROLL
    assert normalize_pattern("midwestpaylink.com") == "@midwestpaylink.com"
    assert normalize_pattern("@Midwestpaylink.com") == "@midwestpaylink.com"
    assert normalize_pattern("mailto:kturner@midwestpaylink.com") == PAYROLL


@pytest.mark.parametrize("junk", ["", "   ", "two words", "a@b", "@nodot", "a@@b.com", "@.com", "@x."])
def test_junk_patterns_are_refused(junk):
    with pytest.raises(ValueError):
        normalize_pattern(junk)


def test_domain_match_is_exact_not_suffix():
    """"@paylink.com" must not catch midwestpaylink.com, or subdomains."""
    assert is_private(PAYROLL, ["@midwestpaylink.com"])
    assert is_private(PAYROLL, [PAYROLL])
    assert not is_private(PAYROLL, ["@paylink.com"])
    assert not is_private("x@mail.midwestpaylink.com", ["@midwestpaylink.com"])
    assert not is_private("x@example.com", ["y@example.com"])


# --- the ingest skip ------------------------------------------------------

def payroll_mail():
    return {
        "subject": "Q3 payroll",
        "from_name": "Keith Turner",
        "from_email": PAYROLL,
        "to": ["craigz@expertsvc.com"],
        "body": "Payroll figures attached.",
    }


def test_private_sender_is_skipped():
    verdict = decide(
        norm(payroll_mail()), internal_domain=INTERNAL,
        website_senders=WEBSITE_SENDERS, mailboxes=MAILBOXES,
        private_senders=["@midwestpaylink.com"],
    )
    assert verdict.action is Action.SKIP
    assert "Private sender" in verdict.reason


def test_private_beats_the_note_on_existing_thread_path():
    """A private sender replying on a tracked thread must vanish too, not
    surface as a note on someone's queue item."""
    verdict = decide(
        norm(payroll_mail()), internal_domain=INTERNAL,
        website_senders=WEBSITE_SENDERS, mailboxes=MAILBOXES,
        existing_message_id=7,
        private_senders=[PAYROLL],
    )
    assert verdict.action is Action.SKIP


def test_ingest_skips_a_listed_sender_end_to_end(db):
    db.add(PrivateSender(pattern="@midwestpaylink.com"))
    db.commit()
    action = ingest_one(db, graph_message(payroll_mail()), "craigz@expertsvc.com")
    assert action == "skip"
    assert db.execute(select(Message)).scalars().all() == []


def test_ordinary_mail_still_flows_past_the_list(db):
    db.add(PrivateSender(pattern="@midwestpaylink.com"))
    db.commit()
    action = ingest_one(db, graph_message(fx.CONTACT_FORM_LEAK), "craigz@expertsvc.com")
    assert action == "create"


# --- the purge ------------------------------------------------------------

def test_purge_takes_the_whole_thread_and_nothing_else(db):
    keith = queued(db, PAYROLL)
    db.add(Note(message_id=keith.id, author_name="Keith Turner", body_text="…"))
    db.add(Reply(message_id=keith.id, body_text="…"))
    customer = queued(db, "dwhitfield@example.com", from_name="Dana Whitfield")
    db.commit()

    assert purge_matching(db, "@midwestpaylink.com") == 1
    db.commit()

    assert db.execute(select(Message)).scalars().all() == [customer]
    assert db.execute(select(Note)).scalars().all() == []
    assert db.execute(select(Reply)).scalars().all() == []


# --- the API --------------------------------------------------------------

def test_adding_an_entry_blocks_and_purges(client, db):
    queued(db, PAYROLL)
    queued(db, "invoices@midwestpaylink.com", from_name="Midwest Paylink")
    survivor = queued(db, "dwhitfield@example.com", from_name="Dana Whitfield")

    response = client.post("/api/private-senders", json={"pattern": "Midwestpaylink.com"})
    assert response.status_code == 201
    data = response.json()
    assert data["entry"]["pattern"] == "@midwestpaylink.com"
    assert data["entry"]["added_by"]["display_name"] == "Craig Zumdick"
    assert data["purged"] == 2
    assert [m.id for m in db.execute(select(Message)).scalars()] == [survivor.id]

    listed = client.get("/api/private-senders").json()
    assert [e["pattern"] for e in listed] == ["@midwestpaylink.com"]


def test_duplicates_and_junk_are_400(client):
    assert client.post("/api/private-senders", json={"pattern": PAYROLL}).status_code == 201
    assert client.post("/api/private-senders", json={"pattern": PAYROLL.upper()}).status_code == 400
    assert client.post("/api/private-senders", json={"pattern": "not a sender"}).status_code == 400


def test_removing_an_entry(client, db):
    entry_id = client.post(
        "/api/private-senders", json={"pattern": PAYROLL}
    ).json()["entry"]["id"]

    assert client.delete(f"/api/private-senders/{entry_id}").status_code == 204
    assert client.get("/api/private-senders").json() == []
    assert client.delete(f"/api/private-senders/{entry_id}").status_code == 404
