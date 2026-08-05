"""Normalisation and the skip / note / create decision."""

from html import escape

from app.mail.normalize import normalize
from app.mail.rules import Action, decide, is_automated, is_internal
from app.models import FORM_CONTACT, FORM_INSTALL

from . import fixtures as fx

WEBSITE_SENDERS = ["website@expertsvc.com"]
INTERNAL = "expertsvc.com"
MAILBOXES = [
    "craigz@expertsvc.com",
    "joyce@expertsvc.com",
    "kasiew@expertsvc.com",
    "info@expertsvc.com",
    "queue@expertsvc.com",
]
FORWARD_BOX = "queue@expertsvc.com"


def graph_message(fixture, *, msg_id="AAA", conversation="CONV", html=True):
    """Wrap a fixture in the shape Microsoft Graph actually returns."""
    body = fixture["body"]
    return {
        "id": msg_id,
        "conversationId": conversation,
        "subject": fixture["subject"],
        "from": {
            "emailAddress": {
                "name": fixture["from_name"],
                "address": fixture["from_email"],
            }
        },
        "toRecipients": [
            {"emailAddress": {"address": a}} for a in fixture.get("to", [])
        ],
        "ccRecipients": [
            {"emailAddress": {"address": a}} for a in fixture.get("cc", [])
        ],
        "body": {
            "contentType": "html" if html else "text",
            # Shaped like the real thing: opens with a bare <meta charset>, and
            # the text is HTML-escaped — which matters, because quoted headers
            # contain "<addr@example.com>" and an unescaped one would be eaten
            # as a tag.
            "content": (
                '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
                + escape(body).replace("\n", "<br>")
            )
            if html
            else body,
        },
        "hasAttachments": bool(fixture.get("attachments")),
        "attachments": [{"name": n} for n in fixture.get("attachments", [])],
        "receivedDateTime": "2026-07-29T11:26:00Z",
    }


def norm(fixture, mailbox="craigz@expertsvc.com", **kwargs):
    return normalize(
        graph_message(fixture, **kwargs),
        mailbox,
        website_senders=WEBSITE_SENDERS,
        forward_mailbox=FORWARD_BOX,
    )


# --- normalisation -------------------------------------------------------

def test_website_form_sender_is_replaced_by_the_real_customer():
    """Without this, every form appears to be from website@ and replies go
    back to ourselves."""
    msg = norm(fx.CONTACT_FORM_LEAK)
    assert msg.from_email == "dwhitfield@example.com"
    assert msg.from_name == "Dana Whitfield"
    assert msg.form_type == FORM_CONTACT
    assert not msg.needs_review


def test_install_form_is_recognised_and_attributed():
    msg = norm(fx.INSTALL_FORM)
    assert msg.form_type == FORM_INSTALL
    assert msg.from_email == "ncole@example.com"
    assert "Tired of dragging a hose" in msg.body_clean


def test_unreadable_form_is_still_queued_but_flagged():
    """A layout change must not silently drop submissions."""
    msg = norm(fx.CONTACT_FORM_MALFORMED)
    assert msg.needs_review
    assert "back zone" in msg.body_clean
    assert msg.review_reason


def test_attachments_are_counted():
    msg = norm(fx.FORWARDED_HOA)
    assert msg.attachment_count == 2
    assert "Video.mov" in msg.attachment_names


def test_external_forward_keeps_the_forwarder_as_the_contact():
    """An HOA manager passing on a resident's report is still our contact —
    replying to the resident would send our answer to a stranger."""
    msg = norm(fx.FORWARDED_HOA, mailbox="craigz@expertsvc.com")
    assert msg.from_email == "rachel.doyle@examplehoa.com"
    assert msg.source == "graph"


def test_staff_forward_to_the_queue_box_recovers_the_customer():
    """Same message, arriving at queue@ because a colleague put it there."""
    msg = norm(fx.FORWARDED_HOA, mailbox=FORWARD_BOX)
    assert msg.source == "forwarded"
    assert msg.forwarded_by == "rachel.doyle@examplehoa.com"
    assert msg.from_email == "aprescott@example.com"
    assert msg.subject == "ABERDEEN- Union KY."


def test_quotes_and_signatures_are_out_of_the_classifier_text():
    msg = norm(fx.THREADED_REPLY)
    assert "Estimate for the new sensor" in msg.body_clean
    assert "www.expertsvc.com" not in msg.body_clean
    assert "Not sure of any model" not in msg.body_clean
    # The office still gets the whole thing on screen.
    assert "Not sure of any model" in msg.body_text


# --- decisions -----------------------------------------------------------

def test_website_sender_is_never_treated_as_internal():
    """The bug this whole module exists to prevent: skipping our own domain
    would discard every website form."""
    msg = norm(fx.CONTACT_FORM_LEAK)
    assert not is_internal(msg, INTERNAL, WEBSITE_SENDERS)

    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES,
    )
    assert verdict.action is Action.CREATE


def test_ordinary_customer_mail_creates_an_item():
    msg = norm(fx.DIRECT_URGENT)
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES,
    )
    assert verdict.action is Action.CREATE


def test_duplicate_across_mailboxes_is_skipped():
    """One email to four Expert addresses is the normal case, not an edge one."""
    msg = norm(fx.DIRECT_URGENT)
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES, already_ingested=True,
    )
    assert verdict.action is Action.SKIP


def test_automated_mail_is_skipped():
    msg = norm(fx.NO_REPLY_VENDOR)
    assert is_automated(msg.from_email)
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES,
    )
    assert verdict.action is Action.SKIP


def test_bulk_headers_mark_automated_mail():
    assert is_automated("news@supplier.example", {"List-Unsubscribe": "<mailto:x>"})
    assert not is_automated("someone@example.com", {"Subject": "Leak"})


def test_internal_chatter_with_no_existing_item_is_skipped():
    msg = norm(fx.INTERNAL_REPLY)
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES,
    )
    assert verdict.action is Action.SKIP


def test_internal_reply_on_a_known_thread_becomes_a_note():
    """The office replies to each other on the customer's thread. That's
    context for the item, not a second item."""
    msg = norm(fx.INTERNAL_REPLY)
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES, existing_message_id=42,
    )
    assert verdict.action is Action.NOTE
    assert verdict.message_id == 42
    assert not verdict.reopen


def test_customer_reply_reopens_a_handled_item():
    msg = norm(fx.DIRECT_URGENT)
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES, existing_message_id=7, existing_is_handled=True,
    )
    assert verdict.action is Action.NOTE
    assert verdict.reopen


def test_mail_only_cc_ing_a_monitored_mailbox_is_kept():
    """Craig was Cc-only on a live leak report. To-only matching drops it."""
    msg = norm(fx.FORWARDED_HOA)
    assert "craigz@expertsvc.com" not in msg.to_recipients
    assert "craigz@expertsvc.com" in msg.cc_recipients
    verdict = decide(
        msg, internal_domain=INTERNAL, website_senders=WEBSITE_SENDERS,
        mailboxes=MAILBOXES,
    )
    assert verdict.action is Action.CREATE
