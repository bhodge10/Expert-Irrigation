"""Website form submissions.

Three different forms feed the same inbox, and none of them puts the customer
in the From header — every one is sent by website@expertsvc.com. Without this
module every form in the queue would appear to be from the website itself, and
replying would send mail to ourselves.

  contact          expertsvc.com/contact/        positional, NO field labels
  install          expertsvc.com/new-customer/   "Label: value"
  service_request  expertsvc.com/new-customer/   "Label: value", different questions

Both new-customer forms share a Page URL, so the subject line is what tells
them apart.

See docs/mail-patterns.md for where these shapes came from.
"""

import re
from dataclasses import dataclass, field

from ..models import FORM_CONTACT, FORM_INSTALL, FORM_SERVICE
from .cleaning import strip_form_boilerplate

WEBSITE_SENDER = "website@expertsvc.com"

_EMAIL = re.compile(r"^[\w.+-]+@[\w.-]+\.\w{2,}$")
# Deliberately loose: real submissions arrive as 8597607103, 859-760-7103,
# (859) 760-7103.
_PHONE = re.compile(r"^\+?[\d\s().-]{9,20}$")
_PAGE_URL = re.compile(r"^\s*Page URL:\s*(\S+)", re.IGNORECASE | re.MULTILINE)

_STATE_LINE = re.compile(r"^(KY|OH|IN):\s*(.*)$", re.IGNORECASE)


@dataclass
class ParsedForm:
    """What we recovered from a form body."""

    form_type: str
    from_name: str = ""
    from_email: str = ""
    phone: str = ""
    address: str = ""
    message: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    # False when the layout didn't match and we fell back to raw text. The
    # caller should still create a queue item — just without trusting these.
    confident: bool = True


# Evidence that the body in front of us really is a form, rather than a reply
# on a thread that once contained one.
_CONTACT_EVIDENCE = re.compile(
    r"Virtual Estimate for Outdoor Lighting|expertsvc\.com/contact/", re.IGNORECASE
)
_INSTALL_EVIDENCE = re.compile(
    r"new construction or existing|driving you to have a new sprinkler system",
    re.IGNORECASE,
)
_SERVICE_EVIDENCE = re.compile(
    r"backflow preventer|searching for a new Irrigation contractor", re.IGNORECASE
)


def detect_form_type(subject: str, body: str) -> str | None:
    """Which form, if any, produced this body.

    The subject alone is never enough. "Re: New Website Form Inquiry" is what
    the office's own replies look like for weeks after a form arrives, and
    treating those as fresh submissions would fill the queue with the office
    talking to itself.

    So: the body must carry evidence of the form's own furniture. Pass the
    quote-stripped body — a reply that merely *quotes* a form is not a form.
    """
    body = body or ""
    subj = (subject or "").lower()

    if _INSTALL_EVIDENCE.search(body):
        return FORM_INSTALL
    if _SERVICE_EVIDENCE.search(body):
        return FORM_SERVICE
    if _CONTACT_EVIDENCE.search(body):
        return FORM_CONTACT

    # No furniture. Only trust the subject if the body still looks structured —
    # covers a form whose boilerplate a mail client has mangled.
    url_match = _PAGE_URL.search(body)
    if url_match:
        url = url_match.group(1).lower()
        if "/contact/" in url:
            return FORM_CONTACT
        if "/new-customer/" in url and "installation" in subj:
            return FORM_INSTALL
        if "/new-customer/" in url:
            return FORM_SERVICE

    return None


def _labelled_fields(body: str) -> dict[str, str]:
    """Pull 'Label: value' pairs, folding the KY/OH/IN sub-lines into one."""
    fields: dict[str, str] = {}
    pending_state_label: str | None = None

    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue

        state = _STATE_LINE.match(line)
        if state and pending_state_label:
            # Only one of KY:/OH:/IN: carries a value.
            value = state.group(2).strip()
            if value:
                fields[pending_state_label] = f"{state.group(1).upper()}: {value}"
            continue

        if ":" not in line:
            continue

        label, _, value = line.partition(":")
        label = label.strip()
        value = value.strip()
        if not label:
            continue

        fields[label] = value
        # "City and state of site to be serviced.:" is a header; its answer is
        # on the following KY/OH/IN lines.
        pending_state_label = label if not value else None

    return fields


def _get(fields: dict[str, str], *names: str) -> str:
    for name in names:
        for label, value in fields.items():
            if label.lower().rstrip(".") == name.lower().rstrip("."):
                return value
    return ""


def _parse_labelled(body: str, form_type: str) -> ParsedForm:
    fields = _labelled_fields(body)

    first = _get(fields, "First Name")
    last = _get(fields, "Last Name")
    name = " ".join(part for part in (first, last) if part).strip()

    address_parts = [
        _get(fields, "Address"),
        _get(fields, "City and state of site to be serviced"),
    ]
    address = ", ".join(p for p in address_parts if p)

    # The questions are the substance of these forms — the free "Message" field
    # is usually empty. Keep the answered ones as the body the office reads.
    skip = {
        "first name", "last name", "phone", "email", "address",
        "date", "time", "page url",
    }
    lines = [
        f"{label}: {value}"
        for label, value in fields.items()
        if value and label.lower().rstrip(".") not in skip
    ]

    return ParsedForm(
        form_type=form_type,
        from_name=name,
        from_email=_get(fields, "Email"),
        phone=_get(fields, "Phone"),
        address=address,
        message="\n".join(lines),
        fields=fields,
        confident=bool(name and _get(fields, "Email")),
    )


def _parse_contact(body: str) -> ParsedForm:
    """The contact form has no labels — seven values, then the message.

    Position-dependent and therefore brittle. If the form is ever reordered
    this would silently mis-assign every field, so the shape is checked before
    any of it is trusted.
    """
    lines = [ln.strip() for ln in (body or "").split("\n") if ln.strip()]

    # Drop the trailer so it can't be mistaken for message content.
    trimmed: list[str] = []
    for line in lines:
        if line.startswith("---") or re.match(r"^(Date|Time|Page URL):", line, re.I):
            break
        trimmed.append(line)

    if len(trimmed) < 7 or not _EMAIL.match(trimmed[1]) or not _PHONE.match(trimmed[2]):
        # Shape doesn't match. Don't guess — hand back the text and say so.
        return ParsedForm(
            form_type=FORM_CONTACT,
            message=strip_form_boilerplate("\n".join(trimmed)) or (body or "").strip(),
            confident=False,
        )

    name, email, phone, service_type, street, city, postcode = trimmed[:7]
    # The "Virtual Estimate" pitch sits above the trailer, so it survives the
    # trim above and has to go here.
    message = strip_form_boilerplate("\n".join(trimmed[7:]))

    return ParsedForm(
        form_type=FORM_CONTACT,
        from_name=name,
        from_email=email,
        phone=phone,
        address=", ".join(p for p in (street, city, postcode) if p),
        message=message,
        fields={
            "Service type": service_type,
            "Address": street,
            "City": city,
            "Zip": postcode,
        },
        confident=True,
    )


def parse_form(subject: str, body: str) -> ParsedForm | None:
    """Parse a website form body, or return None if this isn't one."""
    form_type = detect_form_type(subject, body)
    if form_type is None:
        return None
    if form_type == FORM_CONTACT:
        return _parse_contact(body)
    return _parse_labelled(body, form_type)
