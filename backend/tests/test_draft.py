"""Reply drafting: tone examples from sent mail, drafts on the right mail,
and graceful failure everywhere. The model itself is always faked."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.draft as draft_mod
import app.ingest as ingest_mod
from app.auth import current_user
from app.classify import Classification
from app.config import settings
from app.db import Base, get_db, utcnow
from app.draft import draft_reply_text, tone_examples
from app.main import app
from app.models import Message, User


@pytest.fixture(autouse=True)
def fresh_tone_cache():
    draft_mod._tone_cache = None
    yield
    draft_mod._tone_cache = None


@pytest.fixture(autouse=True)
def tone_mailboxes(monkeypatch):
    monkeypatch.setattr(
        settings, "monitored_mailboxes", "craigz@expertsvc.com", raising=False
    )


class FakeGraph:
    def __init__(self, sent):
        self._sent = sent
        self.calls = 0

    def sent_messages(self, mailbox, top=50):
        self.calls += 1
        return self._sent


def sent(body_html):
    return {"body": {"contentType": "html", "content": body_html}}


def test_tone_examples_strip_quotes_and_skip_stubs():
    graph = FakeGraph(
        [
            sent(
                "<p>Dana, that hum usually means the transformer tap is loose. "
                "We'll get you on the schedule.</p>"
                "<p>Craig</p>"
                "<p>From: Dana &lt;d@example.com&gt;<br>Sent: Tuesday, August 11<br>"
                "Subject: transformer</p><p>original text</p>"
            ),
            sent("<p>ok thanks</p>"),  # too short to teach anything
        ]
    )
    block = tone_examples(graph)
    assert "transformer tap" in block
    assert "original text" not in block  # quoted history stripped
    assert "ok thanks" not in block


def test_tone_examples_are_cached():
    graph = FakeGraph(
        [sent("<p>A real reply with plenty of length to count as a tone example.</p>")]
    )
    tone_examples(graph)
    tone_examples(graph)
    assert graph.calls == 1


def test_tone_fetch_failure_returns_empty_not_raise():
    class BrokenGraph:
        def sent_messages(self, mailbox, top=50):
            raise RuntimeError("graph down")

    assert tone_examples(BrokenGraph()) == ""


def test_unconfigured_drafting_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    assert (
        draft_reply_text(
            None,
            from_name="Dana",
            from_email="d@example.com",
            subject="Leak",
            body="Water everywhere",
            mailbox="craigz@expertsvc.com",
        )
        is None
    )


def test_draft_uses_the_model_and_survives_failure(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        draft_mod, "_call_draft", lambda system, user: "Dana, on our way.\n\nCraig"
    )
    text = draft_reply_text(
        None,
        from_name="Dana",
        from_email="d@example.com",
        subject="Leak",
        body="Water everywhere",
        mailbox="craigz@expertsvc.com",
    )
    assert text == "Dana, on our way.\n\nCraig"

    def boom(system, user):
        raise RuntimeError("api down")

    monkeypatch.setattr(draft_mod, "_call_draft", boom)
    assert (
        draft_reply_text(
            None,
            from_name="Dana",
            from_email="d@example.com",
            subject="Leak",
            body="Water everywhere",
            mailbox="craigz@expertsvc.com",
        )
        is None
    )


# ---------------------------------------------------------------------------
# Ingest wiring: who gets a draft at ingest


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def _ingest_with(db, monkeypatch, classification):
    from tests.fixtures import DIRECT_URGENT
    from tests.test_ingest_rules import graph_message

    monkeypatch.setattr(ingest_mod, "classify_new", lambda *a, **k: classification)
    drafted = []

    def fake_draft(graph, **kwargs):
        drafted.append(kwargs["from_email"])
        return "Drafted."

    monkeypatch.setattr(ingest_mod, "draft_reply_text", fake_draft)
    monkeypatch.setattr(settings, "internal_domain", "expertsvc.com", raising=False)
    monkeypatch.setattr(settings, "ingest_max_age_days", 0, raising=False)

    ingest_mod.ingest_one(
        db, graph_message(DIRECT_URGENT, msg_id=f"M-{classification.queue}"),
        "craigz@expertsvc.com",
    )
    return drafted


def test_service_mail_is_drafted_at_ingest(db, monkeypatch):
    c = Classification(queue="service", confidence=90, is_urgent=True, reasons=["x"], source="model")
    assert len(_ingest_with(db, monkeypatch, c)) == 1
    message = db.query(Message).one()
    assert message.draft_reply == "Drafted."


def test_other_mail_is_not_drafted_at_ingest(db, monkeypatch):
    c = Classification(queue="undetermined", confidence=95, is_urgent=False, reasons=["x"], source="model")
    assert _ingest_with(db, monkeypatch, c) == []
    assert db.query(Message).one().draft_reply is None


def test_auto_handled_mail_is_not_drafted(db, monkeypatch):
    c = Classification(
        queue="service", confidence=100, is_urgent=False, reasons=["x"],
        source="sender-rule", auto_handle=True,
    )
    assert _ingest_with(db, monkeypatch, c) == []


# ---------------------------------------------------------------------------
# The on-demand endpoint


@pytest.fixture
def client(db):
    joyce = db.query(User).first()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: joyce
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def message(db):
    msg = Message(
        mailbox="craigz@expertsvc.com",
        from_name="Dana Whitfield",
        from_email="d@example.com",
        subject="Zone 3 stuck on",
        body_text="The zone will not shut off.",
        received_at=utcnow(),
        queue="service",
        confidence=90,
    )
    db.add(msg)
    db.commit()
    return msg


def test_draft_endpoint_saves_and_returns(client, db, message, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "ms_tenant_id", "", raising=False)
    monkeypatch.setattr(
        draft_mod, "draft_reply_text", lambda graph, **k: "Dana, we'll take a look.\n\nCraig"
    )

    res = client.post(f"/api/messages/{message.id}/draft")
    assert res.status_code == 200
    assert res.json()["draft_reply"].startswith("Dana, we'll take a look.")
    assert db.get(Message, message.id).draft_reply is not None


def test_draft_endpoint_requires_the_key(client, message, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    res = client.post(f"/api/messages/{message.id}/draft")
    assert res.status_code == 400


def test_draft_endpoint_surfaces_failure(client, message, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "ms_tenant_id", "", raising=False)
    monkeypatch.setattr(draft_mod, "draft_reply_text", lambda graph, **k: None)
    res = client.post(f"/api/messages/{message.id}/draft")
    assert res.status_code == 502
