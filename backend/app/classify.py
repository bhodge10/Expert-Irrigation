"""Sorting a message into a queue: office-taught rules first, then the model.

Two layers, in order:

1. **Sender rules** — deterministic, instant, absolute. Derived from the
   classification_events feedback trail, so the office teaches them just by
   working the queue: move a sender's mail to Sales once and their next email
   goes straight to Sales; press "Not valid" on the same sender twice and
   their mail stops appearing at all. No model call, no API cost, effect on
   the very next poll.

2. **The Claude model** — everything the rules don't decide. The system
   prompt is prompts/classify.md (read fresh on every call, so Craig can edit
   it without touching Python), and recent human verdicts ride along as
   worked examples, which is how corrections become accuracy.

Everything here is read-only against the database and never raises out of
classify_new() — a classifier failure means the message files as unsorted
Other at zero confidence, exactly as Phase 2 filed everything. Never block
ingestion, never drop a message.
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    IGNORED,
    KIND_CONFIRMATION,
    KIND_CORRECTION,
    KIND_REJECTION,
    UNDETERMINED,
    ClassificationEvent,
    Message,
)

log = logging.getLogger(__name__)

# The reason shown while a message is unsorted. classify strips it before
# appending real reasons; ingest uses it as the placeholder.
UNSORTED_REASON = "Not sorted yet"

# How many "Not valid" verdicts on a sender before their mail auto-files.
# One click could be a slip; two is a policy.
REJECTIONS_TO_AUTOFILE = 2

# Worked examples per model call, most recent human verdicts first.
FEW_SHOT_LIMIT = 6

# Body text sent to the model, per message and per example.
BODY_CHARS = 6000
EXAMPLE_CHARS = 400


@dataclass
class Classification:
    queue: str
    confidence: int
    is_urgent: bool
    reasons: list[str] = field(default_factory=list)
    # "sender-rule" | "model" | "unsorted" — recorded nowhere yet, but callers
    # and tests read it, and the backfill prints it.
    source: str = "unsorted"
    # Sender was rejected repeatedly: file it handled so it never hits the queue.
    auto_handle: bool = False


UNSORTED = Classification(
    queue=UNDETERMINED,
    confidence=0,
    is_urgent=False,
    reasons=[UNSORTED_REASON],
    source="unsorted",
)


class _ModelVerdict(BaseModel):
    """The strict shape the model must return."""

    queue: Literal["service", "sales", "ignored", "undetermined"]
    confidence: int = Field(ge=0, le=100)
    is_urgent: bool
    reasons: list[str] = Field(min_length=1, max_length=4)


# ---------------------------------------------------------------------------
# Layer 1 — sender rules from the feedback trail


def _sender_events(db: Session, from_email: str) -> list[ClassificationEvent]:
    """Human verdicts on earlier mail from this sender, newest first."""
    if not from_email:
        return []
    return list(
        db.execute(
            select(ClassificationEvent)
            .join(Message, ClassificationEvent.message_id == Message.id)
            .where(
                func.lower(Message.from_email) == from_email.lower(),
                ClassificationEvent.changed_by.isnot(None),
            )
            .order_by(ClassificationEvent.id.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )


def sender_verdict(db: Session, from_email: str) -> Classification | None:
    """What the office has already taught us about this sender, if anything."""
    events = _sender_events(db, from_email)
    if not events:
        return None

    rejections = [e for e in events if e.kind == KIND_REJECTION]
    latest = events[0]

    if latest.kind == KIND_REJECTION and len(rejections) >= REJECTIONS_TO_AUTOFILE:
        return Classification(
            queue=IGNORED,
            confidence=100,
            is_urgent=False,
            reasons=[
                f"Mail from this sender was marked not valid "
                f"{len(rejections)} times — filed automatically"
            ],
            source="sender-rule",
            auto_handle=True,
        )

    if latest.kind in (KIND_CORRECTION, KIND_CONFIRMATION):
        verb = "moved" if latest.kind == KIND_CORRECTION else "worked"
        return Classification(
            queue=latest.to_queue,
            confidence=100,
            is_urgent=False,
            reasons=[
                f"The office previously {verb} mail from this sender "
                f"{'to' if verb == 'moved' else 'in'} {latest.to_queue}"
            ],
            source="sender-rule",
        )

    # A single rejection isn't a rule yet — let the model decide, with the
    # rejection riding along as a worked example.
    return None


# ---------------------------------------------------------------------------
# Layer 2 — the model


def _snippet(message: Message, limit: int) -> str:
    body = (message.body_clean or message.body_text or "").strip()
    return body[:limit]


def few_shot_examples(db: Session, limit: int = FEW_SHOT_LIMIT) -> str:
    """Recent human verdicts, rendered as worked examples for the prompt.

    Corrections are the model's failures; confirmations are the balancing
    successes; rejections teach what this office considers noise. All three
    go in — training on failures alone over-corrects (decisions.md).
    """
    events = (
        db.execute(
            select(ClassificationEvent)
            .where(ClassificationEvent.changed_by.isnot(None))
            .order_by(ClassificationEvent.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    blocks: list[str] = []
    for event in events:
        message = event.message
        if message is None:
            continue
        head = (
            f"From: {message.from_name} <{message.from_email}>\n"
            f"Subject: {message.subject}\n"
            f"Body: {_snippet(message, EXAMPLE_CHARS)}"
        )
        if event.kind == KIND_CORRECTION:
            verdict = (
                f"The sorting said {event.from_queue or 'nothing'}; the office "
                f"corrected it to {event.to_queue}."
            )
        elif event.kind == KIND_REJECTION:
            verdict = (
                "The office marked this as noise nobody needed to read. "
                "Correct answer: queue=ignored, not urgent."
            )
        else:  # confirmation
            verdict = f"The office worked this in {event.to_queue} — the sort was right."
        blocks.append(f"{head}\n=> {verdict}")

    if not blocks:
        return ""
    joined = "\n\n".join(blocks)
    return (
        "Here is how the office judged recent sorting decisions. Treat these "
        f"as ground truth for this business:\n\n{joined}\n\n---\n\n"
    )


def _system_prompt() -> str:
    return settings.classify_prompt_path.read_text(encoding="utf-8")


_client = None


def _anthropic_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=60.0
        )
    return _client


def _call_model(system: str, user_content: str) -> _ModelVerdict | None:
    """One classification call. Returns None on refusal or truncation."""
    response = _anthropic_client().messages.parse(
        model=settings.classify_model,
        max_tokens=8000,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
        output_format=_ModelVerdict,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        log.warning("Classifier gave no verdict (stop_reason=%s)", response.stop_reason)
        return None
    return response.parsed_output


def model_verdict(
    db: Session,
    *,
    mailbox: str,
    from_name: str,
    from_email: str,
    subject: str,
    body: str,
) -> Classification | None:
    if not settings.classification_configured:
        return None

    user_content = (
        f"{few_shot_examples(db)}"
        "Classify this message.\n\n"
        f"Arrived at mailbox: {mailbox}\n"
        f"From: {from_name} <{from_email}>\n"
        f"Subject: {subject}\n"
        f"Body:\n{(body or '').strip()[:BODY_CHARS]}"
    )

    verdict = _call_model(_system_prompt(), user_content)
    if verdict is None:
        return None

    queue = verdict.queue
    reasons = list(verdict.reasons)
    # The confidence floor is enforced in code, not just asked for in the
    # prompt: below it, the guess isn't a filing — the message waits for a
    # human, with the model's leaning preserved as a reason.
    floor = settings.classify_confidence_floor
    if queue != UNDETERMINED and verdict.confidence < floor:
        reasons.append(
            f"Leaned {queue} at {verdict.confidence}% — below the {floor}% "
            "bar, so a human decides"
        )
        queue = UNDETERMINED

    return Classification(
        queue=queue,
        confidence=verdict.confidence,
        is_urgent=verdict.is_urgent,
        reasons=reasons,
        source="model",
    )


# ---------------------------------------------------------------------------
# The entry point


def classify_new(
    db: Session,
    *,
    mailbox: str,
    from_name: str,
    from_email: str,
    subject: str,
    body: str,
) -> Classification:
    """Sort one incoming message. Reads the database, writes nothing, and
    never raises — a failure files the message unsorted, same as Phase 2."""
    try:
        taught = sender_verdict(db, from_email)
        if taught is not None:
            return taught
        modeled = model_verdict(
            db,
            mailbox=mailbox,
            from_name=from_name,
            from_email=from_email,
            subject=subject,
            body=body,
        )
        if modeled is not None:
            return modeled
    except Exception:
        log.exception("Classification failed for mail from %s; filing unsorted", from_email)
    return UNSORTED
