"""The training signals: what each portal action tells the classifier.

Positive actions (assign, mark handled, reply) confirm the sort. Moving a
message to another queue corrects it. The reject button says it should never
have been queued. Every verdict is a classification_events row; nothing else
in the product records them.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import current_user
from app.db import Base, get_db, utcnow
from app.main import app
from app.models import (
    KIND_CONFIRMATION,
    KIND_CORRECTION,
    KIND_MODEL,
    KIND_REJECTION,
    ClassificationEvent,
    Message,
    User,
)


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
def joyce(db):
    user = User(
        email="joyce@expertsvc.com",
        display_name="Joyce Saltzsieder",
        initials="J",
        color="#7A4FA3",
        role="Service scheduling",
        password_hash="x",
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def client(db, joyce):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: joyce
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def message(db):
    msg = Message(
        mailbox="craigz@expertsvc.com",
        from_name="Dana Whitfield",
        from_email="dwhitfield@example.com",
        subject="Zone 3 stuck on",
        body_text="The zone will not shut off.",
        received_at=utcnow(),
        queue="service",
        confidence=70,
    )
    db.add(msg)
    db.flush()
    db.add(
        ClassificationEvent(
            message_id=msg.id,
            from_queue=None,
            to_queue="service",
            confidence=70,
            kind=KIND_MODEL,
        )
    )
    db.commit()
    return msg


def kinds(db, msg):
    return [
        e.kind
        for e in db.execute(
            select(ClassificationEvent)
            .where(ClassificationEvent.message_id == msg.id)
            .order_by(ClassificationEvent.id)
        ).scalars()
    ]


def test_assigning_confirms_the_sort(client, db, message, joyce):
    res = client.post(f"/api/messages/{message.id}/assign", json={"assignee_id": joyce.id})
    assert res.status_code == 200
    assert kinds(db, message) == [KIND_MODEL, KIND_CONFIRMATION]


def test_clearing_an_assignment_says_nothing(client, db, message):
    res = client.post(f"/api/messages/{message.id}/assign", json={"assignee_id": None})
    assert res.status_code == 200
    assert kinds(db, message) == [KIND_MODEL]


def test_marking_handled_confirms_once_not_twice(client, db, message, joyce):
    client.post(f"/api/messages/{message.id}/assign", json={"assignee_id": joyce.id})
    client.post(f"/api/messages/{message.id}/status", json={"status": "handled"})
    # Two positive actions, one verdict — repeat confirmations are noise.
    assert kinds(db, message) == [KIND_MODEL, KIND_CONFIRMATION]


def test_replying_confirms_the_sort(client, db, message):
    res = client.post(
        f"/api/messages/{message.id}/reply",
        json={"body_text": "On our way.", "mark_handled": True},
    )
    assert res.status_code == 200
    assert kinds(db, message) == [KIND_MODEL, KIND_CONFIRMATION]


def test_moving_queues_records_a_correction_not_a_confirmation(client, db, message):
    res = client.post(f"/api/messages/{message.id}/queue", json={"queue": "sales"})
    assert res.status_code == 200
    assert kinds(db, message) == [KIND_MODEL, KIND_CORRECTION]
    # Working the message after correcting it must not also "confirm" it —
    # the human verdict is already on record.
    client.post(f"/api/messages/{message.id}/status", json={"status": "handled"})
    assert kinds(db, message) == [KIND_MODEL, KIND_CORRECTION]


def test_reject_records_the_verdict_and_clears_the_queue(client, db, message, joyce):
    res = client.post(f"/api/messages/{message.id}/reject")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "handled"
    assert body["rejected_by"]["id"] == joyce.id
    assert kinds(db, message) == [KIND_MODEL, KIND_REJECTION]

    # Pressing it twice is one verdict, and the message row survives — the
    # brief's rule: never drop a message on the floor.
    client.post(f"/api/messages/{message.id}/reject")
    assert kinds(db, message) == [KIND_MODEL, KIND_REJECTION]
    assert db.get(Message, message.id) is not None
