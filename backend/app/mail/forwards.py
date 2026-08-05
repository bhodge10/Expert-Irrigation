"""Recovering the original sender from a forwarded message.

When someone forwards mail to the queue address, the From header becomes the
person who forwarded it. The actual customer is buried in a header block inside
the body:

    From: Tony Piper <piperan26@example.com>
    Sent: Wednesday, July 29, 2026 7:26 AM
    To: Stephanie Niemer <stephanie@example.com>
    Subject: ABERDEEN- Union KY.

This is the least reliable code in the project, because every mail client
formats that block slightly differently. So the contract is deliberate:

  **A failed parse never loses the message.** The caller still creates a queue
  item using the forwarder as the sender, flagged so a human can fix it.
  Wrong sender is recoverable; silently dropped is not.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

# "Name <addr@example.com>" or a bare address.
_ADDRESS = re.compile(
    r"(?:\"?(?P<name>[^\"<>]*?)\"?\s*)?<?(?P<email>[\w.+-]+@[\w.-]+\.\w{2,})>?"
)

_FROM_LINE = re.compile(r"^\s*From:\s*(?P<value>.+?)\s*$", re.IGNORECASE)
_FIELD_LINE = re.compile(
    r"^\s*(?P<key>Sent|Date|To|Subject|Cc|Reply-To):\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)

_FORWARD_BANNERS = (
    re.compile(r"^\s*Begin forwarded message:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*(Original|Forwarded) message\s*-{2,}\s*$", re.IGNORECASE),
)

# "FW: ", "Fwd: ", "Fw : " and friends, possibly stacked.
_FWD_SUBJECT = re.compile(r"^\s*(?:(?:FWD?|Fwd)\s*:\s*)+", re.IGNORECASE)


@dataclass
class ForwardedOriginal:
    """The message that was forwarded, as far as we could recover it."""

    from_name: str = ""
    from_email: str = ""
    subject: str = ""
    sent_at: datetime | None = None
    body: str = ""
    # False when we couldn't find a header block. Caller falls back to the
    # forwarder and flags the message for a human.
    confident: bool = False


def looks_forwarded(subject: str, body: str) -> bool:
    """Cheap check before doing the real work."""
    if _FWD_SUBJECT.match(subject or ""):
        return True
    lines = (body or "").split("\n")
    return _find_header_block(lines) is not None


def strip_forward_prefix(subject: str) -> str:
    """'FW: Fwd: Leak in Aberdeen' -> 'Leak in Aberdeen'."""
    return _FWD_SUBJECT.sub("", subject or "").strip()


def _find_header_block(lines: list[str]) -> int | None:
    """Index of a 'From:' that starts a real forwarded header block."""
    for i, line in enumerate(lines):
        if any(b.match(line) for b in _FORWARD_BANNERS):
            # Apple Mail puts the banner above the headers.
            for j in range(i + 1, min(i + 8, len(lines))):
                if _FROM_LINE.match(lines[j]):
                    return j
            continue
        if _FROM_LINE.match(line):
            # Require a second header nearby, so prose beginning "From:" isn't
            # mistaken for a header block.
            following = [ln for ln in lines[i + 1 : i + 6] if ln.strip()]
            if any(_FIELD_LINE.match(ln) for ln in following):
                return i
    return None


def _parse_address(value: str) -> tuple[str, str]:
    match = _ADDRESS.search(value or "")
    if not match:
        return (value or "").strip(), ""
    name = (match.group("name") or "").strip().strip(",")
    email = match.group("email").strip()
    if not name:
        name = email.split("@")[0].replace(".", " ").title()
    return name, email


def _parse_sent(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass
    # Outlook writes "Wednesday, July 29, 2026 7:26 AM", which isn't RFC 2822.
    cleaned = re.sub(r"^\s*\w+day,\s*", "", value)
    for fmt in ("%B %d, %Y %I:%M %p", "%B %d, %Y at %I:%M:%S %p", "%d %B %Y %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def parse_forwarded(subject: str, body: str) -> ForwardedOriginal:
    """Pull the original sender, subject and body out of a forward."""
    lines = (body or "").split("\n")
    start = _find_header_block(lines)

    if start is None:
        return ForwardedOriginal(
            subject=strip_forward_prefix(subject),
            body=(body or "").strip(),
            confident=False,
        )

    from_value = _FROM_LINE.match(lines[start]).group("value")
    name, email = _parse_address(from_value)

    headers: dict[str, str] = {}
    cursor = start + 1
    # Header blocks are broken up by the blank lines Outlook litters
    # everywhere, so allow gaps rather than stopping at the first one.
    blanks = 0
    while cursor < len(lines) and blanks < 6:
        line = lines[cursor]
        if not line.strip():
            blanks += 1
            cursor += 1
            continue
        match = _FIELD_LINE.match(line)
        if not match:
            break
        headers[match.group("key").lower()] = match.group("value")
        blanks = 0
        cursor += 1

    original_body = "\n".join(lines[cursor:]).strip()

    return ForwardedOriginal(
        from_name=name,
        from_email=email,
        subject=(headers.get("subject") or strip_forward_prefix(subject)).strip(),
        sent_at=_parse_sent(headers.get("sent") or headers.get("date") or ""),
        body=original_body,
        # An address is the one thing we genuinely need; without it there's
        # nobody to reply to and the forwarder has to be used instead.
        confident=bool(email),
    )
