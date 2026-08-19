"""Drafting a reply in Craig's voice.

The tone comes from Craig's actual sent mail: the last ~50 replies out of
his mailbox, quoted history stripped, fed to the model as examples next to
the instructions in prompts/draft.md (editable, read on every draft). The
examples are cached for an hour so drafting doesn't hammer Graph, and
marked cacheable so repeated drafts inside a few minutes reuse the prompt.

Nothing here sends anything — a draft is text in a column until a human
reads it and presses Send. Failures return None and cost the message its
draft, never its place in the queue.
"""

import logging
import time

from .classify import _anthropic_client
from .config import settings
from .mail.cleaning import strip_quoted
from .mail.html_text import best_body
from .mail.rules import is_private

log = logging.getLogger(__name__)

TONE_FETCH = 50  # sent messages to fetch
TONE_KEEP = 40  # usable examples to keep
TONE_MIN_CHARS = 40  # shorter than this isn't a reply, it's an "ok thanks"
TONE_MAX_CHARS = 500  # per example
TONE_CACHE_SECONDS = 3600

BODY_CHARS = 6000
MAX_TOKENS = 8000

# (fetched_at, private-senders key, rendered examples block)
_tone_cache: tuple[float, frozenset, str] | None = None


def _tone_mailbox() -> str:
    boxes = settings.mailbox_list
    return boxes[0] if boxes else ""


def _recipient_addresses(raw: dict) -> list[str]:
    out = []
    for entry in (raw.get("toRecipients") or []) + (raw.get("ccRecipients") or []):
        address = (entry or {}).get("emailAddress", {}).get("address", "")
        if address:
            out.append(address.strip().lower())
    return out


def tone_examples(graph, private_senders=()) -> str:
    """Craig's recent sent replies, rendered for the prompt. "" when
    unavailable — the draft still happens, just from instructions alone.

    A reply Craig sent TO a private sender is itself private — his half of a
    payroll thread teaches tone as badly as it leaks — so anything addressed
    to the private-senders list is dropped before rendering. The cache keys
    on that list: blocking a sender takes effect on the next draft, not an
    hour later.
    """
    global _tone_cache
    key = frozenset(private_senders)
    if (
        _tone_cache
        and _tone_cache[1] == key
        and time.monotonic() - _tone_cache[0] < TONE_CACHE_SECONDS
    ):
        return _tone_cache[2]

    mailbox = _tone_mailbox()
    if graph is None or not mailbox:
        return _tone_cache[2] if _tone_cache and _tone_cache[1] == key else ""

    try:
        sent = graph.sent_messages(mailbox, top=TONE_FETCH)
    except Exception:
        log.exception("Couldn't fetch sent mail for tone examples")
        return _tone_cache[2] if _tone_cache and _tone_cache[1] == key else ""

    examples: list[str] = []
    for raw in sent:
        if any(is_private(a, private_senders) for a in _recipient_addresses(raw)):
            continue
        body_obj = raw.get("body") or {}
        html = body_obj.get("content") if body_obj.get("contentType") == "html" else None
        text = best_body(raw.get("bodyPreview"), html or body_obj.get("content"))
        text = strip_quoted(text or "").strip()
        if len(text) < TONE_MIN_CHARS:
            continue
        examples.append(text[:TONE_MAX_CHARS])
        if len(examples) >= TONE_KEEP:
            break

    if not examples:
        return ""
    block = (
        "Here are replies Craig actually sent recently. Match how they "
        "sound:\n\n" + "\n\n---\n\n".join(examples)
    )
    _tone_cache = (time.monotonic(), key, block)
    return block


def _system_blocks(tone: str) -> list[dict]:
    blocks = [
        {"type": "text", "text": settings.draft_prompt_path.read_text(encoding="utf-8")}
    ]
    if tone:
        blocks.append(
            {"type": "text", "text": tone, "cache_control": {"type": "ephemeral"}}
        )
    return blocks


def _call_draft(system: list[dict], user_content: str) -> str | None:
    response = _anthropic_client().messages.create(
        model=settings.classify_model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    if response.stop_reason != "end_turn":
        log.warning("Drafting stopped early (stop_reason=%s)", response.stop_reason)
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


def draft_reply_text(
    graph,
    *,
    from_name: str,
    from_email: str,
    subject: str,
    body: str,
    mailbox: str,
    private_senders=(),
) -> str | None:
    """One draft. Returns None on any failure — never raises, never blocks."""
    if not settings.classification_configured:
        return None
    try:
        user_content = (
            "Draft a reply to this message.\n\n"
            f"It arrived at: {mailbox}\n"
            f"From: {from_name} <{from_email}>\n"
            f"Subject: {subject}\n"
            f"Body:\n{(body or '').strip()[:BODY_CHARS]}"
        )
        return _call_draft(
            _system_blocks(tone_examples(graph, private_senders)), user_content
        )
    except Exception:
        log.exception("Drafting failed for mail from %s", from_email)
        return None
