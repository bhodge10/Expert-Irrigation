"""Private messages: flagged by the sorting, visible only to their recipients.

The companion to test_private_senders.py. Blocking stops mail at the door;
this flag handles what does come in but is nobody else's business — the
server hides it from every login it wasn't addressed to, keeps it out of
few-shot examples, and never auto-drafts it. The tone sampler tests live
here too: Craig's own replies to private senders stay out of prompts.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import draft as draft_mod
from app import ingest as ingest_mod
from app.auth import current_user
from app.classify import Classification, few_shot_examples, sender_verdict
from app.db import Base, get_db, utcnow
from app.main import app
from app.models import (
    KIND_CONFIRMATION,
    KIND_CORRECTION,
    ClassificationEvent,
    Message,
    User,
)

from .test_ingest_rules import graph_message


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


def make_user(db, email, name):
    user = User(
        email=email,
        display_name=name,
        initials=name[0],
        color="#1F7A47",
        role="Office",
        password_hash="x",
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def craig(db):
    return make_user(db, "craigz@expertsvc.com", "Craig Zumdick")


@pytest.fixture
def joyce(db):
    return make_user(db, "joyce@expertsvc.com", "Joyce Saltzsieder")


def client_as(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def teardown_overrides():
    yield
    app.dependency_overrides.clear()


def add_mail(db, *, private=False, visible_to=",craigz@expertsvc.com,", **kw):
    msg = Message(
        mailbox=kw.get("mailbox", "craigz@expertsvc.com"),
        from_name=kw.get("from_name", "Keith Turner"),
        from_email=kw.get("from_email", "kturner@midwestpaylink.com"),
        subject=kw.get("subject", "(private)"),
        body_text=kw.get("body", "…"),
        body_clean=kw.get("body", "…"),
        received_at=utcnow(),
        queue=kw.get("queue", "undetermined"),
        confidence=kw.get("confidence", 95),
        is_private=private,
        visible_to=visible_to,
    )
    db.add(msg)
    db.commit()
    return msg


# --- who sees what --------------------------------------------------------

def test_private_mail_is_invisible_to_the_rest_of_the_office(
    db, craig, joyce, teardown_overrides
):
    private = add_mail(db, private=True, subject="Payroll")
    public = add_mail(
        db, from_name="Dana", from_email="d@example.com", subject="Leak"
    )

    for_craig = client_as(db, craig).get("/api/messages").json()
    assert {m["id"] for m in for_craig["messages"]} == {private.id, public.id}
    assert for_craig["counts"]["undetermined"] == 2

    for_joyce = client_as(db, joyce).get("/api/messages").json()
    assert {m["id"] for m in for_joyce["messages"]} == {public.id}
    assert for_joyce["counts"]["undetermined"] == 1


def test_everyone_it_was_addressed_to_sees_it(db, craig, joyce, teardown_overrides):
    """An email to Craig AND Joyce dedupes into one queue item — both of its
    recipients keep sight of it, whichever mailbox it filed under."""
    both = add_mail(
        db, private=True, visible_to=",craigz@expertsvc.com,joyce@expertsvc.com,"
    )
    assert client_as(db, joyce).get(f"/api/messages/{both.id}").status_code == 200


def test_detail_and_actions_404_for_outsiders(db, craig, joyce, teardown_overrides):
    private = add_mail(db, private=True)
    as_joyce = client_as(db, joyce)
    assert as_joyce.get(f"/api/messages/{private.id}").status_code == 404
    assert (
        as_joyce.post(
            f"/api/messages/{private.id}/assign", json={"assignee_id": None}
        ).status_code
        == 404
    )


def test_recipient_can_release_and_office_can_flag(
    db, craig, joyce, teardown_overrides
):
    private = add_mail(db, private=True, subject="Payroll")
    as_craig = client_as(db, craig)

    released = as_craig.post(
        f"/api/messages/{private.id}/private", json={"is_private": False}
    )
    assert released.status_code == 200
    assert not released.json()["is_private"]
    assert client_as(db, joyce).get(f"/api/messages/{private.id}").status_code == 200

    # Joyce spots something personal the model missed and flags it. She isn't
    # in the audience, but flagging must never hide a message from yourself.
    reflagged = client_as(db, joyce).post(
        f"/api/messages/{private.id}/private", json={"is_private": True}
    )
    assert reflagged.status_code == 200
    db.expire_all()
    row = db.get(Message, private.id)
    assert ",joyce@expertsvc.com," in row.visible_to
    assert client_as(db, joyce).get(f"/api/messages/{private.id}").status_code == 200


# --- what the learning loop sees ------------------------------------------

def test_private_mail_stays_out_of_few_shot_examples(db, craig):
    private = add_mail(db, private=True, subject="Payroll Q3", body="Salary table")
    public = add_mail(
        db, from_name="Dana", from_email="d@example.com",
        subject="Zone 3 stuck", body="The zone will not shut off.",
    )
    for message in (private, public):
        db.add(
            ClassificationEvent(
                message_id=message.id,
                from_queue="undetermined",
                to_queue="service",
                changed_by=craig.id,
                confidence=100,
                kind=KIND_CORRECTION,
            )
        )
    db.commit()

    block = few_shot_examples(db)
    assert "Zone 3 stuck" in block
    assert "Payroll Q3" not in block
    assert "Salary table" not in block


def test_sender_rules_never_launder_privacy_away(db, craig):
    """A queue verdict on a private message still teaches the sender's queue —
    but the next email from them arrives private too."""
    earlier = add_mail(db, private=True)
    db.add(
        ClassificationEvent(
            message_id=earlier.id,
            from_queue="undetermined",
            to_queue="undetermined",
            changed_by=craig.id,
            confidence=100,
            kind=KIND_CONFIRMATION,
        )
    )
    db.commit()

    taught = sender_verdict(db, "kturner@midwestpaylink.com")
    assert taught is not None
    assert taught.is_private


# --- ingest ---------------------------------------------------------------

def payroll_fixture():
    return {
        "subject": "Q3 payroll",
        "from_name": "Keith Turner",
        "from_email": "kturner@midwestpaylink.com",
        "to": ["craigz@expertsvc.com"],
        "cc": ["megank@expertsvc.com"],
        "body": "Payroll figures attached.",
    }


def test_ingest_stores_flag_and_audience_and_skips_the_draft(db, monkeypatch):
    monkeypatch.setattr(
        ingest_mod,
        "classify_new",
        lambda *a, **k: Classification(
            queue="service", confidence=95, is_urgent=False,
            source="model", is_private=True,
        ),
    )
    monkeypatch.setattr(
        ingest_mod,
        "draft_reply_text",
        lambda *a, **k: pytest.fail("private mail must not be drafted"),
    )

    assert ingest_mod.ingest_one(db, graph_message(payroll_fixture()), "craigz@expertsvc.com") == "create"

    row = db.execute(select(Message)).scalars().one()
    assert row.is_private
    assert row.visible_to == ",craigz@expertsvc.com,megank@expertsvc.com,"
    assert row.draft_reply is None


# --- the tone sampler -----------------------------------------------------

class FakeGraph:
    def __init__(self, sent):
        self._sent = sent

    def sent_messages(self, mailbox, top=50):
        return self._sent


def sent_reply(text, to):
    return {
        "body": {"contentType": "text", "content": text},
        "toRecipients": [{"emailAddress": {"address": to}}],
    }


@pytest.fixture(autouse=True)
def fresh_tone_cache():
    draft_mod._tone_cache = None
    yield
    draft_mod._tone_cache = None


def test_replies_to_private_senders_stay_out_of_tone_examples():
    graph = FakeGraph(
        [
            sent_reply(
                "Keith, the Q3 numbers look right — bonuses go out Friday as discussed.",
                "kturner@midwestpaylink.com",
            ),
            sent_reply(
                "Dana, that hum usually means a loose transformer tap. We'll swing by.",
                "d@example.com",
            ),
        ]
    )
    block = draft_mod.tone_examples(graph, ["@midwestpaylink.com"])
    assert "transformer tap" in block
    assert "bonuses" not in block


def test_blocking_a_sender_invalidates_the_tone_cache():
    graph = FakeGraph(
        [
            sent_reply(
                "Keith, the Q3 numbers look right — bonuses go out Friday as discussed.",
                "kturner@midwestpaylink.com",
            )
        ]
    )
    assert "bonuses" in draft_mod.tone_examples(graph, [])
    # Same hour, new block entry: the cached hour must not keep leaking.
    assert draft_mod.tone_examples(graph, ["@midwestpaylink.com"]) == ""
