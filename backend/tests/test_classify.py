"""The classifier's two layers: office-taught sender rules, then the model.

The model itself is faked — these tests prove the plumbing: rules outrank the
model, feedback becomes few-shot examples, and every failure files the
message unsorted instead of blocking ingestion.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import classify
from app.classify import (
    UNSORTED_REASON,
    Classification,
    classify_new,
    few_shot_examples,
    sender_verdict,
)
from app.config import settings
from app.db import Base, utcnow
from app.models import (
    KIND_CONFIRMATION,
    KIND_CORRECTION,
    KIND_MODEL,
    KIND_REJECTION,
    ClassificationEvent,
    Message,
    User,
)

VENDOR = "promos@vendor.example.com"
CUSTOMER = "dwhitfield@example.com"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(
        User(
            email="joyce@expertsvc.com",
            display_name="Joyce Saltzsieder",
            initials="J",
            color="#7A4FA3",
            role="Service scheduling",
            password_hash="x",
        )
    )
    session.commit()
    yield session
    session.close()


def add_mail(db, from_email, subject="Sprinkler question", body="Zone 3 is stuck on."):
    message = Message(
        mailbox="craigz@expertsvc.com",
        from_name=from_email.split("@")[0],
        from_email=from_email,
        subject=subject,
        body_text=body,
        body_clean=body,
        received_at=utcnow(),
        queue="undetermined",
        confidence=0,
    )
    db.add(message)
    db.flush()
    return message


def add_verdict(db, message, kind, to_queue="undetermined", from_queue="undetermined"):
    joyce = db.execute(select(User)).scalars().first()
    db.add(
        ClassificationEvent(
            message_id=message.id,
            from_queue=from_queue,
            to_queue=to_queue,
            changed_by=joyce.id,
            confidence=100,
            kind=kind,
        )
    )
    db.commit()


def test_a_correction_teaches_the_sender_rule(db):
    earlier = add_mail(db, CUSTOMER)
    add_verdict(db, earlier, KIND_CORRECTION, to_queue="sales")

    c = sender_verdict(db, CUSTOMER)
    assert c is not None
    assert c.queue == "sales"
    assert c.confidence == 100
    assert c.source == "sender-rule"
    assert not c.auto_handle


def test_a_confirmation_teaches_too(db):
    earlier = add_mail(db, CUSTOMER)
    add_verdict(db, earlier, KIND_CONFIRMATION, to_queue="service", from_queue="service")

    c = sender_verdict(db, CUSTOMER)
    assert c is not None
    assert c.queue == "service"


def test_one_rejection_is_not_a_rule(db):
    earlier = add_mail(db, VENDOR)
    add_verdict(db, earlier, KIND_REJECTION)

    assert sender_verdict(db, VENDOR) is None


def test_two_rejections_auto_file_the_sender(db):
    for _ in range(2):
        earlier = add_mail(db, VENDOR)
        add_verdict(db, earlier, KIND_REJECTION)

    c = sender_verdict(db, VENDOR)
    assert c is not None
    assert c.queue == "ignored"
    assert c.auto_handle
    assert "not valid" in c.reasons[0]


def test_sender_matching_is_case_insensitive(db):
    earlier = add_mail(db, CUSTOMER)
    add_verdict(db, earlier, KIND_CORRECTION, to_queue="sales")

    assert sender_verdict(db, CUSTOMER.upper()) is not None


def test_few_shot_examples_render_the_feedback(db):
    corrected = add_mail(db, CUSTOMER, subject="Bid for 12 lots")
    add_verdict(db, corrected, KIND_CORRECTION, to_queue="sales")
    rejected = add_mail(db, VENDOR, subject="50% off mulch")
    add_verdict(db, rejected, KIND_REJECTION)

    text = few_shot_examples(db)
    assert "Bid for 12 lots" in text
    assert "corrected it to sales" in text
    assert "50% off mulch" in text
    assert "queue=ignored" in text


def test_no_feedback_means_no_example_block(db):
    assert few_shot_examples(db) == ""


def test_unconfigured_classifier_files_unsorted(db, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    c = classify_new(
        db,
        mailbox="craigz@expertsvc.com",
        from_name="Dana",
        from_email=CUSTOMER,
        subject="Zone stuck on",
        body="Water everywhere.",
    )
    assert c.source == "unsorted"
    assert c.queue == "undetermined"
    assert c.confidence == 0
    assert c.reasons == [UNSORTED_REASON]


def test_sender_rule_wins_without_touching_the_model(db, monkeypatch):
    earlier = add_mail(db, CUSTOMER)
    add_verdict(db, earlier, KIND_CORRECTION, to_queue="sales")
    monkeypatch.setattr(
        classify, "model_verdict", lambda *a, **k: pytest.fail("model was called")
    )

    c = classify_new(
        db,
        mailbox="craigz@expertsvc.com",
        from_name="Dana",
        from_email=CUSTOMER,
        subject="Another one",
        body="More work please.",
    )
    assert c.source == "sender-rule"
    assert c.queue == "sales"


def test_model_verdict_is_applied(db, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        classify,
        "_call_model",
        lambda system, user: classify._ModelVerdict(
            queue="service",
            confidence=95,
            is_urgent=True,
            reasons=["Active leak at an existing installation"],
        ),
    )

    c = classify_new(
        db,
        mailbox="craigz@expertsvc.com",
        from_name="Dana",
        from_email=CUSTOMER,
        subject="Water running down the driveway",
        body="A zone will not shut off and water is pooling.",
    )
    assert c.source == "model"
    assert c.queue == "service"
    assert c.confidence == 95
    assert c.is_urgent
    assert c.reasons == ["Active leak at an existing installation"]


def test_below_the_confidence_floor_goes_to_undetermined(db, monkeypatch):
    """A 72% service guess isn't a filing — a human decides, with the
    model's leaning preserved as a reason."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        classify,
        "_call_model",
        lambda system, user: classify._ModelVerdict(
            queue="service",
            confidence=72,
            is_urgent=False,
            reasons=["Might be a repair"],
        ),
    )

    c = classify_new(
        db,
        mailbox="craigz@expertsvc.com",
        from_name="Dana",
        from_email=CUSTOMER,
        subject="Transformer humming",
        body="Half the run is out, is it time to replace it?",
    )
    assert c.queue == "undetermined"
    assert c.confidence == 72
    assert any("Leaned service" in r for r in c.reasons)


def test_a_model_crash_files_unsorted_instead_of_raising(db, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)

    def boom(system, user):
        raise RuntimeError("api down")

    monkeypatch.setattr(classify, "_call_model", boom)

    c = classify_new(
        db,
        mailbox="craigz@expertsvc.com",
        from_name="Dana",
        from_email=CUSTOMER,
        subject="Hello",
        body="Hi.",
    )
    assert c.source == "unsorted"


def test_ingested_mail_from_a_rejected_sender_arrives_handled(db, monkeypatch):
    """End to end through create_message: known noise never hits the queue."""
    from app.ingest import create_message
    from app.mail.normalize import NormalizedMessage

    for _ in range(2):
        earlier = add_mail(db, VENDOR)
        add_verdict(db, earlier, KIND_REJECTION)

    c = classify_new(
        db,
        mailbox="craigz@expertsvc.com",
        from_name="Vendor",
        from_email=VENDOR,
        subject="Buy our stuff",
        body="Deals deals deals.",
    )
    msg = NormalizedMessage(
        graph_message_id="M-NOISE",
        conversation_id="C1",
        mailbox="craigz@expertsvc.com",
        from_name="Vendor",
        from_email=VENDOR,
        subject="Buy our stuff",
        body_text="Deals deals deals.",
        body_html=None,
        body_clean="Deals deals deals.",
        received_at=utcnow(),
    )
    record = create_message(db, msg, c)

    assert record.status == "handled"
    assert record.queue == "ignored"
    event = record.classification_events[0]
    assert event.kind == KIND_MODEL
    assert event.changed_by is None
