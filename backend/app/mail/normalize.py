"""Turning a raw Graph message into something the queue can use.

Order matters here, and it isn't obvious:

    1. flatten the HTML          (real bodies are HTML-only)
    2. strip the quoted history  (find what was actually just said)
    3. unwrap a forward          (recover the original, if staff forwarded it)
    4. parse a website form      (recover the customer, who is in the body)
    5. clean for the classifier

Form parsing must come *after* unwrapping, or a forwarded form is read as the
covering note rather than the form. And form detection runs on the unquoted
text, or every "Re: New Website Form Inquiry" in the office looks like a fresh
submission.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .cleaning import clean_for_classification, strip_quoted
from .forms import parse_form
from .forwards import looks_forwarded, parse_forwarded, strip_forward_prefix
from .html_text import best_body


@dataclass
class NormalizedMessage:
    graph_message_id: str = ""
    conversation_id: str | None = None
    mailbox: str = ""

    from_name: str = ""
    from_email: str = ""
    subject: str = ""
    body_text: str = ""
    body_html: str | None = None
    body_clean: str = ""
    received_at: datetime | None = None

    to_recipients: list[str] = field(default_factory=list)
    cc_recipients: list[str] = field(default_factory=list)

    source: str = "graph"
    forwarded_by: str | None = None
    form_type: str | None = None

    attachment_count: int = 0
    attachment_names: list[str] = field(default_factory=list)

    # True when a parser wasn't sure. The message still reaches the queue —
    # it's just marked so a human knows the sender may be wrong.
    needs_review: bool = False
    review_reason: str = ""

    @property
    def sender_domain(self) -> str:
        return self.from_email.split("@")[-1].lower() if "@" in self.from_email else ""


def _addresses(recipients) -> list[str]:
    """Pull plain addresses out of Graph's recipient structures."""
    out = []
    for entry in recipients or []:
        address = (entry or {}).get("emailAddress", {}).get("address", "")
        if address:
            out.append(address.strip().lower())
    return out


def _clean_filename(name: str) -> str:
    # .msg exports carry trailing NULs; Graph is cleaner but costs nothing.
    return (name or "").replace("\x00", "").strip()


def normalize(
    raw: dict,
    mailbox: str,
    *,
    website_senders: list[str],
    forward_mailbox: str = "",
) -> NormalizedMessage:
    """Build a NormalizedMessage from one Graph message resource."""
    sender = (raw.get("from") or raw.get("sender") or {}).get("emailAddress", {}) or {}
    from_email = (sender.get("address") or "").strip().lower()
    from_name = (sender.get("name") or "").strip() or from_email

    subject = (raw.get("subject") or "").strip()
    body_obj = raw.get("body") or {}
    body_html = body_obj.get("content") if body_obj.get("contentType") == "html" else None
    raw_text = raw.get("bodyPreview") if body_obj.get("contentType") != "html" else None
    if body_obj.get("contentType") != "html":
        raw_text = body_obj.get("content") or raw_text

    body_text = best_body(raw_text, body_html or body_obj.get("content"))

    attachments = [
        _clean_filename(a.get("name", "")) for a in (raw.get("attachments") or [])
    ]

    msg = NormalizedMessage(
        graph_message_id=raw.get("id") or "",
        conversation_id=raw.get("conversationId"),
        mailbox=mailbox.lower(),
        from_name=from_name,
        from_email=from_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        received_at=raw.get("receivedDateTime"),
        to_recipients=_addresses(raw.get("toRecipients")),
        cc_recipients=_addresses(raw.get("ccRecipients")),
        attachment_count=len(attachments) or int(bool(raw.get("hasAttachments"))),
        attachment_names=[a for a in attachments if a],
    )

    # The newest content, with the thread history removed.
    new_part = strip_quoted(body_text)
    search_subject, search_body = subject, new_part

    # --- forwards ---------------------------------------------------------
    # Only re-attribute the sender when a colleague deliberately put this in
    # the queue address. When an outside party forwards us something — an HOA
    # manager passing on a resident's complaint — the forwarder IS our contact
    # and the person to reply to. Overriding them would send our answer to a
    # stranger.
    arrived_at_forward_box = bool(
        forward_mailbox and mailbox.lower() == forward_mailbox.lower()
    )
    if arrived_at_forward_box and looks_forwarded(subject, body_text):
        original = parse_forwarded(subject, body_text)
        msg.source = "forwarded"
        msg.forwarded_by = from_email
        msg.subject = original.subject or strip_forward_prefix(subject)

        if original.confident:
            msg.from_name = original.from_name
            msg.from_email = original.from_email
            search_subject, search_body = msg.subject, original.body
        else:
            # Couldn't find the original sender. Keep the colleague as sender
            # so the item still exists and someone can correct it — never drop
            # the message.
            msg.needs_review = True
            msg.review_reason = (
                "Forwarded, but the original sender couldn't be read. "
                "Check who this should be from before replying."
            )
            search_body = original.body or new_part

    # --- website forms ----------------------------------------------------
    # These arrive from website@expertsvc.com; the customer is in the body.
    is_website = from_email in website_senders or msg.source == "forwarded"
    if is_website:
        parsed = parse_form(search_subject, search_body)
        if parsed is not None:
            msg.form_type = parsed.form_type
            if parsed.confident:
                msg.from_name = parsed.from_name
                msg.from_email = parsed.from_email
                if parsed.message:
                    msg.body_clean = parsed.message
                if parsed.address or parsed.phone:
                    detail = " · ".join(p for p in (parsed.phone, parsed.address) if p)
                    msg.body_clean = f"{msg.body_clean}\n\n{detail}".strip()
            elif from_email in website_senders:
                # It is a form — we just couldn't read the fields. Still queue
                # it; the text is all there for a human.
                msg.needs_review = True
                msg.review_reason = (
                    "Website form didn't match the expected layout. "
                    "The customer's details may be wrong — check the message."
                )

    if not msg.body_clean:
        msg.body_clean = clean_for_classification(body_text)

    return msg
