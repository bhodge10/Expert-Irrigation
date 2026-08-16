"""End to end: fake Graph -> parsing -> rules -> database.

Uses a real (in-memory) database and a stand-in Graph client, so the whole
ingest path is exercised without a Microsoft tenant.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base
from app.ingest import poll_mailbox
from app.models import ClassificationEvent, MailboxState, Message, Note, User

from . import fixtures as fx
from .test_ingest_rules import graph_message

MAILBOXES = "craigz@expertsvc.com,joyce@expertsvc.com,info@expertsvc.com"
FORWARD_BOX = "queue@expertsvc.com"


class FakeGraph:
    """Stands in for GraphClient. Records what would have been written."""

    def __init__(self, per_mailbox: dict[str, list[dict]]):
        self._per_mailbox = per_mailbox
        self.tagged: list[tuple[str, str, list[str]]] = []
        self.replies: list[tuple[str, str, str]] = []
        self.headers: dict[str, dict[str, str]] = {}
        self.tag_should_fail = False

    def delta_messages(self, mailbox, delta_link=None):
        return list(self._per_mailbox.get(mailbox, [])), f"delta-for-{mailbox}"

    def delta_bootstrap(self, mailbox):
        return f"delta-for-{mailbox}"

    def messages_since(self, mailbox, since_iso):
        return list(self._per_mailbox.get(mailbox, []))

    def message_headers(self, mailbox, message_id):
        return self.headers.get(message_id, {})

    def set_categories(self, mailbox, message_id, categories):
        if self.tag_should_fail:
            from app.graph import GraphError

            raise GraphError("Outlook said no")
        self.tagged.append((mailbox, message_id, categories))

    def send_reply(self, mailbox, message_id, body_text):
        self.replies.append((mailbox, message_id, body_text))


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


@pytest.fixture(autouse=True)
def graph_settings(monkeypatch):
    monkeypatch.setattr(settings, "monitored_mailboxes", MAILBOXES, raising=False)
    monkeypatch.setattr(settings, "forward_mailbox", FORWARD_BOX, raising=False)
    monkeypatch.setattr(settings, "outlook_category", "Expert Queue", raising=False)
    monkeypatch.setattr(settings, "internal_domain", "expertsvc.com", raising=False)
    # The fixtures carry a fixed receivedDateTime; the age cutoff is off here
    # so tests don't start failing as that date recedes into the past.
    monkeypatch.setattr(settings, "ingest_max_age_days", 0, raising=False)


def test_age_cutoff_skips_old_mail_but_still_advances_the_delta_link(db, monkeypatch):
    monkeypatch.setattr(settings, "ingest_max_age_days", 7, raising=False)
    old = graph_message(fx.DIRECT_URGENT, msg_id="OLD")
    old["receivedDateTime"] = "2020-01-05T09:00:00Z"
    graph = FakeGraph({"craigz@expertsvc.com": [old]})

    result = poll_mailbox(db, graph, "craigz@expertsvc.com")

    assert result.created == 0
    assert result.skipped == 1
    state = db.execute(select(MailboxState)).scalars().one()
    assert state.delta_link == "delta-for-craigz@expertsvc.com"


def test_website_form_becomes_a_queue_item_with_the_real_customer(db):
    graph = FakeGraph(
        {"craigz@expertsvc.com": [graph_message(fx.CONTACT_FORM_LEAK, msg_id="M1")]}
    )
    result = poll_mailbox(db, graph, "craigz@expertsvc.com")

    assert result.created == 1
    message = db.execute(select(Message)).scalars().one()
    assert message.from_email == "dwhitfield@example.com"
    assert message.mailbox == "craigz@expertsvc.com"
    assert message.form_type == "contact"
    assert "large leak" in message.body_clean


def test_ingest_logs_a_classification_event(db):
    """Even the not-yet-classified state is recorded, so the audit trail has
    no gap when Phase 3 turns the classifier on."""
    graph = FakeGraph(
        {"craigz@expertsvc.com": [graph_message(fx.CONTACT_FORM_LEAK, msg_id="M1")]}
    )
    poll_mailbox(db, graph, "craigz@expertsvc.com")

    event = db.execute(select(ClassificationEvent)).scalars().one()
    assert event.from_queue is None
    assert event.changed_by is None


def test_same_message_in_two_mailboxes_creates_one_item(db):
    """The normal case: customers mail several Expert addresses at once."""
    raw = graph_message(fx.DIRECT_URGENT, msg_id="SHARED", conversation="C1")
    graph = FakeGraph(
        {
            "craigz@expertsvc.com": [raw],
            "joyce@expertsvc.com": [raw],
            "info@expertsvc.com": [raw],
        }
    )
    for mailbox in ("craigz@expertsvc.com", "joyce@expertsvc.com", "info@expertsvc.com"):
        poll_mailbox(db, graph, mailbox)

    assert db.execute(select(Message)).scalars().all().__len__() == 1


def test_internal_reply_on_a_known_thread_becomes_a_note_not_an_item(db):
    """Otherwise the queue fills with the office talking to itself."""
    graph = FakeGraph(
        {
            "craigz@expertsvc.com": [
                graph_message(fx.CONTACT_FORM_LEAK, msg_id="M1", conversation="C9"),
                graph_message(fx.INTERNAL_REPLY, msg_id="M2", conversation="C9"),
            ]
        }
    )
    result = poll_mailbox(db, graph, "craigz@expertsvc.com")

    assert result.created == 1
    assert result.noted == 1
    message = db.execute(select(Message)).scalars().one()
    note = db.execute(select(Note)).scalars().one()
    assert note.message_id == message.id
    # The author was matched to a portal user, so the note is attributed.
    assert note.user_id is not None
    assert "Billy scheduled" in note.body_text


def test_customer_reply_reopens_a_handled_item(db):
    graph = FakeGraph(
        {
            "craigz@expertsvc.com": [
                graph_message(fx.DIRECT_URGENT, msg_id="M1", conversation="C3")
            ]
        }
    )
    poll_mailbox(db, graph, "craigz@expertsvc.com")
    message = db.execute(select(Message)).scalars().one()
    message.status = "handled"
    db.commit()

    follow_up = dict(fx.DIRECT_URGENT)
    follow_up["body"] = "Any update on this? We fly out tomorrow."
    graph._per_mailbox["craigz@expertsvc.com"] = [
        graph_message(follow_up, msg_id="M2", conversation="C3")
    ]
    poll_mailbox(db, graph, "craigz@expertsvc.com")

    db.refresh(message)
    assert message.status == "open"
    assert db.execute(select(Note)).scalars().all()


def test_automated_mail_never_reaches_the_queue(db):
    graph = FakeGraph(
        {"craigz@expertsvc.com": [graph_message(fx.NO_REPLY_VENDOR, msg_id="M1")]}
    )
    result = poll_mailbox(db, graph, "craigz@expertsvc.com")
    assert result.created == 0
    assert result.skipped == 1


def test_outlook_tagging_happens_on_create(db):
    graph = FakeGraph(
        {"craigz@expertsvc.com": [graph_message(fx.CONTACT_FORM_LEAK, msg_id="M1")]}
    )
    poll_mailbox(db, graph, "craigz@expertsvc.com")
    assert graph.tagged == [("craigz@expertsvc.com", "M1", ["Expert Queue"])]


def test_a_failed_tag_does_not_lose_the_message(db):
    """Cosmetic write; ingestion must survive it failing."""
    graph = FakeGraph(
        {"craigz@expertsvc.com": [graph_message(fx.CONTACT_FORM_LEAK, msg_id="M1")]}
    )
    graph.tag_should_fail = True
    result = poll_mailbox(db, graph, "craigz@expertsvc.com")

    assert result.created == 1
    assert db.execute(select(Message)).scalars().one()


def test_delta_link_is_stored_so_a_restart_resumes(db):
    graph = FakeGraph(
        {"craigz@expertsvc.com": [graph_message(fx.CONTACT_FORM_LEAK, msg_id="M1")]}
    )
    poll_mailbox(db, graph, "craigz@expertsvc.com")

    state = db.execute(select(MailboxState)).scalars().one()
    assert state.delta_link == "delta-for-craigz@expertsvc.com"
    assert state.last_success_at is not None
    assert state.consecutive_failures == 0


def test_one_bad_message_does_not_stop_the_mailbox(db):
    """A single unparseable message must not block everything behind it."""
    broken = {"id": "BAD", "conversationId": None, "subject": None, "body": None}
    graph = FakeGraph(
        {
            "craigz@expertsvc.com": [
                broken,
                graph_message(fx.CONTACT_FORM_LEAK, msg_id="M2"),
            ]
        }
    )
    result = poll_mailbox(db, graph, "craigz@expertsvc.com")

    assert result.created == 1
    assert db.execute(select(Message)).scalars().one()


def test_staff_forward_to_queue_box_recovers_the_customer(db):
    graph = FakeGraph(
        {FORWARD_BOX: [graph_message(fx.FORWARDED_HOA, msg_id="F1")]}
    )
    poll_mailbox(db, graph, FORWARD_BOX)

    message = db.execute(select(Message)).scalars().one()
    assert message.source == "forwarded"
    assert message.from_email == "aprescott@example.com"
    assert message.forwarded_by == "rachel.doyle@examplehoa.com"
    assert message.attachment_count == 2
