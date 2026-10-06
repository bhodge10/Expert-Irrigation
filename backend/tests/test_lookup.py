"""The ServiceTitan card: how a sender is matched, what the card carries, and
the day-long cache on the message row. Nothing here reaches ServiceTitan —
build_card takes a fake, and the endpoint tests swap the client factory."""

from datetime import timedelta

import pytest

from app import lookup as lookup_mod
from app.config import settings
from app.db import utcnow
from app.lookup import CARD_MAX_AGE, build_card, card_for, expire_cards
from app.models import Message

from .test_private_messages import (  # noqa: F401 — fixtures
    add_mail,
    client_as,
    craig,
    db,
    joyce,
    teardown_overrides,
)

NOW = utcnow()
SOON = (NOW + timedelta(days=2)).isoformat().replace("+00:00", "Z")
LATER = (NOW + timedelta(days=9)).isoformat().replace("+00:00", "Z")
PAST = (NOW - timedelta(days=30)).isoformat().replace("+00:00", "Z")

DANA = {
    "id": 501,
    "name": "Dana Whitfield",
    "type": "Residential",
    "active": True,
    "doNotService": False,
    "address": {"street": "12 Elm Ct", "unit": "", "city": "Hebron", "state": "KY", "zip": "41048"},
}
DANA_CONTACTS = [
    {"type": "MobilePhone", "value": "(859) 555-0100"},
    {"type": "Email", "value": "Dana@Example.com"},
]


class FakeST:
    """Canned ServiceTitan. Records every call so tests can count reads."""

    def __init__(self, *, by_phone=None, by_name=None, contacts=None, memberships=None,
                 jobs=None, appointments=None):
        self.by_phone = by_phone or {}
        self.by_name = by_name or {}
        self.contacts = contacts or {}
        self._memberships = memberships or {}
        self._jobs = jobs or {}
        self._appointments = appointments or {}
        self.calls: list[tuple] = []

    # context-manager so card_for can `with` it like the real client
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def find_customers_by_phone(self, phone):
        self.calls.append(("phone", phone))
        return self.by_phone.get(phone, [])

    def find_customers_by_name(self, name):
        self.calls.append(("name", name))
        return self.by_name.get(name, [])

    def customer_contacts(self, customer_id):
        self.calls.append(("contacts", customer_id))
        return self.contacts.get(customer_id, [])

    def memberships(self, customer_id, status=None):
        self.calls.append(("memberships", customer_id))
        return self._memberships.get(customer_id, [])

    def membership_types(self, ids):
        self.calls.append(("membership_types", tuple(ids)))
        return [{"id": 7, "name": "Gold Plan"}, {"id": 8, "name": "Silver Plan"}]

    def jobs(self, customer_id, limit=20):
        self.calls.append(("jobs", customer_id))
        return self._jobs.get(customer_id, [])

    def job_types(self, ids):
        self.calls.append(("job_types", tuple(ids)))
        return [{"id": 31, "name": "Spring Startup"}, {"id": 32, "name": "Repair"}]

    def appointments(self, job_id):
        self.calls.append(("appointments", job_id))
        return self._appointments.get(job_id, [])


# --- matching ---------------------------------------------------------------


def test_a_phone_number_in_the_signature_matches_first():
    st = FakeST(by_phone={"8595550100": [DANA]}, contacts={501: DANA_CONTACTS})
    card = build_card(
        st,
        from_name="Dana",
        from_email="someone-else@example.com",
        body="Hi — the zone 3 heads won't pop.\n\nDana\n(859) 555-0100",
    )
    assert card.status == "matched"
    assert card.matched_by == "phone"
    assert card.matched_phone == "8595550100"
    assert card.customer.name == "Dana Whitfield"
    assert card.customer.address == "12 Elm Ct, Hebron, KY 41048"
    # The name path was never needed.
    assert ("name", "Dana") not in st.calls


def test_a_name_match_counts_only_when_the_email_is_on_the_account():
    smith_a = {**DANA, "id": 601, "name": "Pat Smith"}
    smith_b = {**DANA, "id": 602, "name": "Pat Smith"}
    st = FakeST(
        by_name={"Pat Smith": [smith_a, smith_b]},
        contacts={
            601: [{"type": "Email", "value": "other@example.com"}],
            602: [{"type": "Email", "value": "PAT@example.com"}],
        },
    )
    card = build_card(st, from_name="Pat Smith", from_email="pat@example.com", body="no number here")
    assert card.status == "matched"
    assert card.matched_by == "name"
    assert card.customer.id == 602


def test_a_name_alone_never_matches():
    st = FakeST(
        by_name={"Pat Smith": [{**DANA, "id": 601, "name": "Pat Smith"}]},
        contacts={601: [{"type": "Email", "value": "other@example.com"}]},
    )
    card = build_card(st, from_name="Pat Smith", from_email="pat@example.com", body="")
    assert card.status == "unmatched"
    assert card.customer is None


def test_unmatched_says_how_hard_it_looked():
    st = FakeST()
    card = build_card(
        st, from_name="Nobody", from_email="n@example.com", body="Call 859-555-0199 or 859.555.0198"
    )
    assert card.status == "unmatched"
    assert card.phones_tried == 2
    assert [c for c in st.calls if c[0] == "phone"] == [("phone", "8595550199"), ("phone", "8595550198")]


def test_no_email_means_no_name_lookup():
    st = FakeST(by_name={"Walk In": [DANA]})
    card = build_card(st, from_name="Walk In", from_email="", body="")
    assert card.status == "unmatched"
    assert ("name", "Walk In") not in st.calls


# --- what the card carries ---------------------------------------------------


def test_the_card_resolves_names_splits_jobs_and_finds_the_next_visit():
    st = FakeST(
        by_phone={"8595550100": [DANA, {**DANA, "id": 502, "name": "Dana W (old)"}]},
        contacts={501: DANA_CONTACTS},
        memberships={
            501: [
                {"id": 1, "membershipTypeId": 8, "status": "Expired", "from": "2024-04-01T00:00:00Z", "to": "2025-03-31T00:00:00Z"},
                {"id": 2, "membershipTypeId": 7, "status": "Active", "from": "2026-04-01T00:00:00Z", "to": None},
            ]
        },
        jobs={
            501: [
                {"id": 900, "jobNumber": "9001", "jobTypeId": 31, "jobStatus": "Scheduled", "summary": "Startup + check zone 3"},
                {"id": 901, "jobNumber": "9002", "jobTypeId": 32, "jobStatus": "Completed", "completedOn": "2026-09-20T15:00:00Z"},
                {"id": 902, "jobNumber": "9003", "jobTypeId": 32, "jobStatus": "Canceled"},
                {"id": 903, "jobNumber": "9004", "jobTypeId": 32, "jobStatus": "Completed", "completedOn": "2026-07-01T15:00:00Z"},
            ]
        },
        appointments={
            900: [
                {"id": 1, "start": PAST, "status": "Done"},
                {"id": 2, "start": LATER, "status": "Scheduled"},
                {"id": 3, "start": SOON, "status": "Scheduled"},
                {"id": 4, "start": "2026-01-01T00:00:00Z", "status": "Canceled"},
            ]
        },
    )
    card = build_card(st, from_name="Dana", from_email="dana@example.com", body="(859) 555-0100")

    assert [m.type for m in card.memberships] == ["Gold Plan", "Silver Plan"]
    assert [m.status for m in card.memberships] == ["Active", "Expired"]

    assert [j.number for j in card.open_jobs] == ["9001"]
    assert card.open_jobs[0].type == "Spring Startup"
    assert card.open_jobs[0].next_appointment.isoformat().replace("+00:00", "Z") == SOON

    assert [j.number for j in card.recent_jobs] == ["9002", "9004"]
    assert card.recent_jobs[0].type == "Repair"
    assert card.recent_jobs[0].completed_on is not None

    assert card.customer.contacts[0].value == "(859) 555-0100"
    assert [m.name for m in card.other_matches] == ["Dana W (old)"]

    # Reference data was asked for once each, by id.
    assert ("membership_types", (7, 8)) in st.calls
    assert ("job_types", (31, 32)) in st.calls


def test_a_do_not_service_flag_comes_through():
    st = FakeST(by_phone={"8595550100": [{**DANA, "doNotService": True}]})
    card = build_card(st, from_name="Dana", from_email="", body="859-555-0100")
    assert card.customer.do_not_service is True


# --- the endpoint and the cache ----------------------------------------------


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "servicetitan_app_key", "k")
    monkeypatch.setattr(settings, "servicetitan_tenant_id", "1")
    monkeypatch.setattr(settings, "servicetitan_client_id", "c")
    monkeypatch.setattr(settings, "servicetitan_client_secret", "s")


def use_fake(monkeypatch, fake):
    """Swap the real client factory for a fake, and count how often it's built."""
    built = {"n": 0}

    def factory():
        built["n"] += 1
        return fake

    monkeypatch.setattr(lookup_mod, "ServiceTitanClient", factory)
    return built


def test_the_card_is_off_until_servicetitan_is_configured(db, craig, teardown_overrides):
    msg = add_mail(db, from_name="Dana", from_email="dana@example.com", body="859-555-0100")
    card = client_as(db, craig).get(f"/api/messages/{msg.id}/servicetitan").json()
    assert card["status"] == "off"


def test_the_card_is_built_once_and_served_from_the_row_after(
    db, craig, teardown_overrides, configured, monkeypatch
):
    fake = FakeST(by_phone={"8595550100": [DANA]}, contacts={501: DANA_CONTACTS})
    built = use_fake(monkeypatch, fake)
    client = client_as(db, craig)
    msg = add_mail(db, from_name="Dana", from_email="dana@example.com", body="859-555-0100")

    first = client.get(f"/api/messages/{msg.id}/servicetitan").json()
    assert first["status"] == "matched"
    assert first["cached"] is False
    assert first["customer"]["name"] == "Dana Whitfield"

    second = client.get(f"/api/messages/{msg.id}/servicetitan").json()
    assert second["cached"] is True
    assert second["customer"] == first["customer"]
    assert built["n"] == 1

    db.refresh(msg)
    assert msg.servicetitan_card["status"] == "matched"
    assert msg.servicetitan_checked_at is not None


def test_refresh_rebuilds_and_an_old_card_rebuilds_on_its_own(
    db, craig, teardown_overrides, configured, monkeypatch
):
    fake = FakeST(by_phone={"8595550100": [DANA]})
    built = use_fake(monkeypatch, fake)
    client = client_as(db, craig)
    msg = add_mail(db, from_name="Dana", from_email="dana@example.com", body="859-555-0100")

    client.get(f"/api/messages/{msg.id}/servicetitan")
    client.get(f"/api/messages/{msg.id}/servicetitan?refresh=true")
    assert built["n"] == 2

    msg.servicetitan_checked_at = utcnow() - CARD_MAX_AGE - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/messages/{msg.id}/servicetitan").json()["cached"] is False
    assert built["n"] == 3


def test_a_failed_lookup_is_reported_and_not_cached(
    db, craig, teardown_overrides, configured, monkeypatch
):
    class Broken(FakeST):
        def find_customers_by_phone(self, phone):
            raise lookup_mod.ServiceTitanError("boom", status=503)

    use_fake(monkeypatch, Broken())
    msg = add_mail(db, from_name="Dana", from_email="dana@example.com", body="859-555-0100")
    card = client_as(db, craig).get(f"/api/messages/{msg.id}/servicetitan").json()
    assert card["status"] == "error"
    assert "boom" in card["error"]
    db.refresh(msg)
    assert msg.servicetitan_card is None


def test_private_mail_hides_its_card_like_everything_else(
    db, craig, joyce, teardown_overrides, configured, monkeypatch
):
    use_fake(monkeypatch, FakeST())
    private = add_mail(db, private=True)
    assert client_as(db, joyce).get(f"/api/messages/{private.id}/servicetitan").status_code == 404
    assert client_as(db, craig).get(f"/api/messages/{private.id}/servicetitan").status_code == 200


def test_cards_older_than_a_day_are_cleared(db):
    fresh = Message(
        mailbox="craigz@expertsvc.com", from_name="A", from_email="a@example.com",
        subject="a", received_at=utcnow(), servicetitan_card={"status": "unmatched"},
        servicetitan_checked_at=utcnow() - timedelta(hours=23),
    )
    stale = Message(
        mailbox="craigz@expertsvc.com", from_name="B", from_email="b@example.com",
        subject="b", received_at=utcnow(), servicetitan_card={"status": "unmatched"},
        servicetitan_checked_at=utcnow() - timedelta(hours=25),
    )
    never = Message(
        mailbox="craigz@expertsvc.com", from_name="C", from_email="c@example.com",
        subject="c", received_at=utcnow(),
    )
    db.add_all([fresh, stale, never])
    db.commit()

    assert expire_cards(db) == 1
    db.expire_all()
    assert fresh.servicetitan_card is not None
    assert stale.servicetitan_card is None and stale.servicetitan_checked_at is None
    assert never.servicetitan_card is None


def test_card_for_leaves_the_row_alone_when_off(db):
    msg = Message(
        mailbox="craigz@expertsvc.com", from_name="A", from_email="a@example.com",
        subject="a", received_at=utcnow(),
    )
    db.add(msg)
    db.commit()
    assert card_for(db, msg).status == "off"
    assert msg.servicetitan_card is None
