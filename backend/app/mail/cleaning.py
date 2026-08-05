"""Cutting an email down to what the sender actually just said.

In the real samples, the new content is routinely two lines sitting above a
page of quoted history and a signature block with a Google-review link. Feed
that to a classifier and it classifies a signature.

Two rules shape everything here:

  Only ever cut from the *bottom*. The new message is at the top; anything we
  trim off the end is recoverable from body_text, which is stored whole.

  When unsure, keep it. A classifier reading slightly too much is a much
  smaller problem than one reading a truncated request.
"""

import re

# --- quoted history -------------------------------------------------------

# "On Tue, 6 May 2026 at 08:42, Craig Zumdick <craigz@…> wrote:"
_ON_WROTE = re.compile(r"^\s*On .{4,120}\bwrote:\s*$", re.IGNORECASE)

# Outlook and Apple Mail forward/reply banners.
_BANNERS = (
    re.compile(r"^\s*Begin forwarded message:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^_{10,}\s*$"),
)

_HEADER_FROM = re.compile(r"^\s*From:\s*\S", re.IGNORECASE)
_HEADER_FOLLOW = re.compile(r"^\s*(Sent|Date|To|Subject|Cc):\s*", re.IGNORECASE)


def find_quote_start(lines: list[str]) -> int | None:
    """Index of the first line that begins quoted history, or None."""
    for i, line in enumerate(lines):
        if _ON_WROTE.match(line):
            return i
        if any(pattern.match(line) for pattern in _BANNERS):
            return i
        # A bare "From:" is ambiguous — people write "From: the back yard".
        # Treat it as a quote header only when another header follows close
        # behind, which is how Outlook always renders it.
        if _HEADER_FROM.match(line):
            lookahead = [ln for ln in lines[i + 1 : i + 5] if ln.strip()]
            if any(_HEADER_FOLLOW.match(ln) for ln in lookahead):
                return i
    return None


def strip_quoted(text: str) -> str:
    """Return only the newest part of a threaded message."""
    if not text:
        return ""

    lines = text.split("\n")
    cut = find_quote_start(lines)
    if cut is None:
        # No banner, but the sender's client may use '>' prefixes instead.
        kept = []
        for line in lines:
            if line.lstrip().startswith(">"):
                break
            kept.append(line)
        return "\n".join(kept).strip()

    return "\n".join(lines[:cut]).strip()


# --- signatures -----------------------------------------------------------

_SIG_DELIMITER = re.compile(r"^\s*--\s*$")

# Anything that clearly belongs to a sign-off rather than a sentence.
_SIG_PATTERNS = (
    re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),  # phone
    re.compile(r"\bwww\.[\w.-]+\b", re.IGNORECASE),
    re.compile(r"\bhttps?://", re.IGNORECASE),
    re.compile(r"^\s*[\w.+-]+@[\w.-]+\.\w+\s*$"),  # a line that is just an email
    re.compile(r"\bext\.?\s*\d+", re.IGNORECASE),
    re.compile(r"\b(Owner|Office|Cell|Mobile|Direct|Fax)\b\s*[:|]?", re.IGNORECASE),
    re.compile(r"Expert Irrigation", re.IGNORECASE),
    re.compile(r"\bCustomer Service Representative\b", re.IGNORECASE),
    re.compile(r"\bInstall Co-?Ordinator\b", re.IGNORECASE),
)

# Lines that reliably mark the very start of a company sign-off.
_SIG_OPENERS = (
    re.compile(r"^\s*Thank[-\s]?you for choosing\b", re.IGNORECASE),
    re.compile(r"^\s*Please take a moment to leave us a (Google )?review", re.IGNORECASE),
    re.compile(r"^\s*Sent from my \w+", re.IGNORECASE),
    re.compile(r"^\s*Get Outlook for \w+", re.IGNORECASE),
)

# A line long enough, and punctuated enough, to be a real sentence.
_PROSE = re.compile(r"[.!?,]")


def _looks_like_signature(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(p.search(stripped) for p in _SIG_PATTERNS):
        return True
    # Short bare lines — a name, a job title — count only as weak evidence and
    # are handled by the caller, not here.
    return False


def _is_prose(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 40:
        return False
    if _looks_like_signature(stripped):
        return False
    return bool(_PROSE.search(stripped))


def strip_signature(text: str) -> str:
    """Trim a trailing signature block.

    Deliberately timid. It walks up from the bottom and stops the moment it
    meets something that reads like a sentence, so a message ending in prose
    loses nothing.
    """
    if not text:
        return ""

    lines = text.split("\n")

    # An explicit "-- " delimiter is unambiguous; honour the last one.
    for i in range(len(lines) - 1, -1, -1):
        if _SIG_DELIMITER.match(lines[i]):
            return "\n".join(lines[:i]).strip()

    # A known opener is also unambiguous.
    for i, line in enumerate(lines):
        if any(p.match(line) for p in _SIG_OPENERS):
            return "\n".join(lines[:i]).strip()

    # Otherwise walk up from the bottom collecting signature-ish lines.
    cut = len(lines)
    hits = 0
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if not line.strip():
            continue
        if _is_prose(line):
            break
        if _looks_like_signature(line):
            hits += 1
            cut = i
            continue
        # A short unremarkable line (a name, "Thanks") — only absorb it if it
        # sits directly above signature lines we've already found.
        if hits and len(line.strip()) < 45:
            cut = i
            continue
        break

    # One stray phone number is not a signature block.
    if hits >= 2:
        return "\n".join(lines[:cut]).strip()
    return text.strip()


# --- website form boilerplate --------------------------------------------

_BOILERPLATE = (
    # Present on every single contact-form submission. Left in, the classifier
    # sees an outdoor-lighting sales pitch on every form and drifts to Sales.
    re.compile(
        r"^\s*Are you interested in a Virtual Estimate for Outdoor Lighting\?.*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"^\s*Please submit image of the front of your house below\??:?\s*$",
               re.IGNORECASE | re.MULTILINE),
)

# The trailer the form platform appends: --- / Date: / Time: / Page URL:
_FORM_TRAILER = re.compile(
    r"\n-{2,}\s*\n(?:\s*(?:Date|Time|Page URL):.*\n?)+\s*$",
    re.IGNORECASE,
)


def strip_form_boilerplate(text: str) -> str:
    """Remove the fixed furniture the website form adds to every submission."""
    if not text:
        return ""

    cleaned = _FORM_TRAILER.sub("\n", text)
    for pattern in _BOILERPLATE:
        cleaned = pattern.sub("", cleaned)

    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


# --- the one callers actually use ----------------------------------------

def clean_for_classification(text: str) -> str:
    """What the model should see: this message, minus the furniture.

    Never destructive — the full text is kept on the message row, so anything
    trimmed here is still on screen for the office.
    """
    if not text:
        return ""

    cleaned = strip_quoted(text)
    cleaned = strip_form_boilerplate(cleaned)
    cleaned = strip_signature(cleaned)

    # If trimming left us with almost nothing, we cut too hard — a two-word
    # reply above a long quote, say. Fall back to the un-trimmed text.
    if len(cleaned.strip()) < 15:
        fallback = strip_form_boilerplate(strip_quoted(text))
        return fallback if fallback.strip() else text.strip()

    return cleaned
