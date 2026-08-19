# Decisions

Choices that were argued once and shouldn't be re-argued from scratch. If you
change one, edit the entry and say why — a decision with a stale reason is
worse than no record.

---

## Render runs a Dockerfile, and render.yaml does not describe production

**Decided:** 2026-08-12 · **Phase:** 1 · **SUPERSEDED 2026-08-16** — the
blueprint was applied: `render.yaml` now IS production (web + worker +
Postgres 16, ~$20/month, walkthrough in render-deploy.md). The trap below
is closed; the free Docker demo service should be deleted, and the laptop
no longer runs anything. The `Dockerfile` remains only as a local-dev
convenience. The entry is kept for the reasoning trail.

The live service is a hand-created **Docker** service on the **free** plan,
built from the `Dockerfile` at the repo root. `render.yaml` describes something
else entirely — a `python` runtime service named `expert-inbox-queue`, plus a
worker and a Postgres 16 database, all on paid plans. It has never been applied.

**Why:** the free plan has no background workers, no `preDeployCommand`, and no
shell. The blueprint can't run there without edits to every service in it.
Adding a Dockerfile got the thing deployed without committing to ~$21/month
before anyone had seen it work.

**What it means while in effect:**

- Migrations and the admin bootstrap run at container start from
  `docker-entrypoint.sh`, not from `preDeployCommand`.
- The database is SQLite inside the container and is destroyed on every deploy
  and idle spin-down. The deployed site is a demo, not a system of record.
- The mail poller (`app/worker.py`) isn't running anywhere. Ingestion is
  local-only until this changes.

**The trap:** `render.yaml` reads like production and isn't. Anyone changing it
and pushing will see no effect at all and reasonably conclude Render is broken.
Left in the repo because it's still the right target — but it is a plan, not a
description.

**Revisit when:** the queue holds anything anyone would miss. That's the moment
to apply the blueprint properly: Postgres for persistence, the worker for
ingestion, and the shell for `manage.py`, which retires the `ADMIN_*`
bootstrap.

---

## The app goes live read-only

**Decided:** 2026-08-09 · **Phase:** 2

Stage one of the Exchange grant is `Application Mail.Read` only. The app can
ingest mail into the queue; it cannot send, modify, or tag anything.
`Mail.ReadWrite` (for tagging, below) and `Mail.Send` (for replies) are
granted later, as stage two in azure-setup.md Part 4c.

**Why:** trust is earned in one direction. A read-only app that misfiles a
message costs a correction; an app that can send costs a wrong email to a
customer. Watching the queue fill correctly for a while before granting write
is cheap insurance, and the upgrade is two cmdlets whenever we're ready.

**What it means while in effect:** `OUTLOOK_CATEGORY` stays empty in `.env`
(disables tagging writes), and Reply in the portal fails with a clear error
recording nothing — expected, not a bug.

**Revisit when:** ingestion has run cleanly and the office wants to answer
from the portal. That's the moment to run stage two and do Part 6.

---

## Outlook gets tagged when a message is queued

**Decided:** 2026-08-01 · **Phase:** 2 · **Deferred 2026-08-09** — waits on
stage two of the read-only rollout above.

The app writes an Outlook **category** onto the source email: `Expert Queue` on
ingest, swapped to `Expert Queue — Handled` when someone completes it in the
portal.

**Why:** Craig needs to trust the portal before he'll stop reading his inbox.
Seeing a tag appear on mail that's already been dealt with is what buys that
trust in month one.

**What it costs:** the app needs `Mail.ReadWrite` instead of `Mail.Read` — so
it can modify and delete mail in the scoped mailboxes, not just read it.
That's a real increase in what a leaked client secret would allow. Accepted
because the Exchange RBAC scope (below) contains it to the monitored
mailboxes, and because rotating the secret is cheap.

**Deliberately not doing:** granting `MailboxSettings.ReadWrite` so the app can
create the colored category itself. That's a third permission for a task you do
once. Create the category by hand in each mailbox instead — see
[azure-setup.md](azure-setup.md).

**Revisit when:** Craig stops looking at Outlook. At that point the tags are
decoration and dropping back to `Mail.Read` is a real security improvement.

---

## Two ways in for mail that misses the queue

**Decided:** 2026-08-01 · **Phase:** 2 · **Forwarding half deferred 2026-08-15**
— `queue@` was never created, and when the monitored set was reconciled against
the tenant (see the next entry) it was dropped from stage one rather than
created. `FORWARD_MAILBOX` stays empty, which disables the forward-parsing path
cleanly. The "New request" button is unaffected. Revive by creating the
mailbox, adding it to the scoping group as a direct member, and setting
`FORWARD_MAILBOX`.

Both:

1. **`queue@expertsvc.com`** — a monitored mailbox staff forward strays to.
2. **A "New request" button** in the portal — for phone calls, walk-ins, and
   anything that was never an email.

**Why both:** they solve different problems. Forwarding catches email that
landed somewhere we don't watch. The button catches *"Mrs. Henderson called
about her backflow test"* — which forwarding can't touch, and which for a
contractor is probably the larger channel.

**Why `queue@` and not `support@`:** it's an internal escape hatch, and a name
customers won't guess keeps it that way. If you later want a public support
address, that's a separate decision — it just becomes another monitored
mailbox, and both can coexist.

**Known rough edge:** a forwarded message arrives `From:` whoever forwarded it,
with the real customer buried in the body. The ingester parses the original
sender back out of the forward block. It will not be perfect across every mail
client. **Rule: if parsing fails, still create the queue item using the
forwarder, flagged for a human.** Never drop a message on the floor.

---

## Three mailboxes are monitored: craigz, megank, joyce

**Decided:** 2026-08-15 · **Phase:** 2 · **Supersedes the brief's mailbox list**

The monitored set is `craigz@`, `megank@`, `joyce@` (all `expertsvc.com`).

**Why:** the brief's list turned out to be partly fictional when checked
against the live tenant during Part 5 verification. `megan@` is actually
`megank@`; `casey@` and `info@` don't exist as recipients at all; `queue@` was
never created (now deferred — see "Two ways in", above). Meanwhile the scoping
group had accumulated five members nobody intended the app to read
(`margaret.greer@` — a shared mailbox — `kasiew@`, `jordanj@`, `olivia@`,
`oswaldov@`); they were pruned the same day. Craig confirmed the three.

**What it means while in effect:** `MONITORED_MAILBOXES` lists exactly these
three; `FORWARD_MAILBOX` is empty; the `Service_and_sales_queue@` group must
contain exactly these three as direct members, because **group membership is
the scope** — anyone added to that group becomes readable by the app. Part 5's
negative test is the check that catches drift.

**Revisit when:** the office wants another mailbox watched — that's a group
membership change plus an edit to `MONITORED_MAILBOXES`, then re-run Part 5.

---

## Mailbox access is scoped with Exchange RBAC, not an application access policy

**Decided:** 2026-08-01 · **Phase:** 2 · **Supersedes the project brief**

The brief specified `New-ApplicationAccessPolicy`. We're using **RBAC for
Applications in Exchange Online** instead.

**Why:** Microsoft now labels application access policies legacy and states
that RBAC for Applications replaces them. RBAC also gives
`Test-ServicePrincipalAuthorization`, which answers "is this actually locked
down?" with a yes or no — exactly the question you'll want to re-ask in six
months and won't want to answer by reading config.

**The trap this avoids.** Permissions from Entra ID and from Exchange RBAC are
**additive**. Consent `Mail.ReadWrite` in the app registration *and* create a
scoped RBAC assignment, and you get the union of the two — which is unscoped.
You would believe the app was limited to five mailboxes while it actually had
the whole tenant. This is the mistake a careful person makes by doing both
"just to be safe."

**So: the app registration gets no Graph API permissions at all.** Mail
permissions are granted only through Exchange RBAC, with a scope attached. If
you ever see mail permissions listed on the app registration, something has
gone wrong — remove them and re-test.

---

## Every portal action is a training signal, and one button says "never should have been here"

**Decided:** 2026-08-16 · **Phase:** 2/3 boundary

Every classification event now carries a `kind`:

- **model** — the automatic sort itself (today the rules engine, Phase 3 the classifier)
- **confirmation** — a human assigned, handled, or replied to the message where
  it landed. First positive action only; repeats are noise. Silent if a human
  verdict already exists — working a message *after* correcting it must not
  also count as "the sort was right".
- **correction** — a human moved it to another queue (what the table always recorded)
- **rejection** — the "Not valid" button: spam, vendor noise, a misfire

**The button's semantics:** rejection records the verdict and marks the
message handled — it leaves the queue but is **never deleted**. The row and
its verdict are the training data, and Reopen undoes a slip. This is also the
portal's stand-in for "delete", which deliberately doesn't exist.

**Why capture confirmations explicitly** when the old entry below said they
were derivable: deriving "handled and never moved" requires deciding *when*
to derive it — a message handled yesterday might be moved tomorrow. An
explicit event stream with an outranking rule (correction/rejection beats
confirmation) has no such ambiguity, and Phase 3 reads it with one query:
`SELECT ... FROM classification_events WHERE kind = ...`.

**What Phase 3 does with them:** corrections and rejections become few-shot
counter-examples; confirmations become the balancing positive examples the
entry below warned would otherwise be missing.

---

## First sync starts at "now" and backfills a window, never the whole mailbox

**Decided:** 2026-08-16 · **Phase:** 2

The first poll of a mailbox does NOT walk its delta from the beginning. It
asks Graph for a delta token at "latest" (no enumeration), then backfills
messages from the last `INGEST_MAX_AGE_DAYS` days (default 7) with a
date-filtered query.

**Why:** the naive first delta walks the mailbox's entire history into
memory. Against Craig's real inbox that was 30+ minutes, a gigabyte of RAM,
and still climbing when we killed it — and Render's free tier has 512MB. The
bootstrap takes seconds. Messages arriving between the two calls appear in
both; the `graph_message_id` dedupe makes that harmless.

**The trade:** mail older than the window never enters the queue. That's the
product decision made the same day: the queue starts with current mail, not
an archaeology dig. Setting `INGEST_MAX_AGE_DAYS=0` (cutoff off) falls back
to the full-history walk — accepted for tiny mailboxes only.

---

## The sorting learns from corrections, but nothing tunes itself silently

**Decided:** 2026-08-01 · **Phase:** 3 · **Built 2026-08-16** — how the three
mechanisms landed:

1. **Sender rules are derived from the feedback trail, not a separate table.**
   The latest human verdict on a sender IS the rule: one correction or
   confirmation files that sender's next mail to the same queue at 100%
   confidence with no model call; two "Not valid" verdicts auto-file the
   sender's mail as handled Other, so known noise never hits the open queue
   (one click could be a slip; two is a policy). Visible and editable by
   definition — the rule is the history the portal already shows, and working
   a message differently rewrites it.
2. **Few-shot:** the last 6 human verdicts (corrections, confirmations, and
   rejections alike) ride along in every classify call as worked examples.
3. **The prompt is `backend/prompts/classify.md`**, read fresh on every
   classification — Craig edits it, saves, and the next email sorts by the
   new rules.

The model is set by `CLASSIFY_MODEL` (running as `claude-sonnet-5`), called
once per new message at ingest, before the database insert so the API call
never holds the SQLite write lock. Any failure — no API key, refusal,
timeout — files the message unsorted in Other at 0%, exactly like Phase 2.
Backfill: `python manage.py classify`.

**Reply drafting (built same day):** service and sales mail also gets a
reply drafted at ingest, in Craig's voice — tone comes from his last ~50
actual sent replies (read via Graph, quoted history stripped, cached an
hour), rules from the editable `backend/prompts/draft.md`. The draft
pre-fills the composer; anything without one (Other-queue mail) gets a
"Draft with AI" button that generates on demand. Nothing sends itself —
a draft is text in a column until a human presses Send, and actual sending
still waits on the stage-two `Mail.Send` grant. Backfill:
`python manage.py draft`.

You cannot fine-tune Claude — Anthropic doesn't offer it. "Getting more
accurate" means three things, and we're doing all three:

1. **Sender and domain rules** — deterministic, instant, absolute. Runs before
   the model. For repeat builders, vendors and the water district this is the
   one that will actually feel like teaching, because the effect is immediate.
2. **Few-shot examples drawn from corrections** — recent corrections get
   injected into the classify prompt as worked examples.
3. **Craig editing `prompts/classify.md`** — least technical, highest leverage.

**The subtlety that matters:** corrections are only the model's *failures*.
Train on failures alone and it over-corrects — starts seeing sales in every
repair. You need confirmations too, and they're already in the data: a message
that was handled and never moved is a quiet "that one was right." Nothing needs
building to capture this; Phase 1's schema already supports deriving it.

**Constraint:** whatever steers the classifier must be visible and editable.
Craig should be able to see the examples currently in play and delete one. A
queue that changes behavior for reasons nobody can inspect is worse than one
that's predictably a bit wrong.

## Private senders: a portal-managed blocklist, because every login sees everything

*2026-08-19*

During Craig's first evaluation week, mail from the payroll company
(`kturner@midwestpaylink.com`) landed in Ignored — correctly sorted, and
still a problem, because the portal has no per-user visibility: every login
sees every queue, Ignored included. Internal mail never enters (the
`@expertsvc.com` skip), but a payroll conversation with an outside vendor
looks exactly like customer mail to the ingestion rules.

The fix is a **private-senders list**, managed in the portal ("Private
senders…" at the bottom of the queue rail). An entry is an address or a
whole domain (stored with a leading `@`); matching mail is skipped at
ingest before anything is stored, and **adding an entry purges whatever
that sender already had in the queue** — items, notes, replies and
classification events, deleted outright, not hidden. Nothing in Outlook is
touched, because ingestion only ever reads. Removing an entry lets new
mail flow again; the purged mail stays gone.

Decisions inside the decision:

- **Every signed-in user can edit the list.** There is no admin role until
  the SSO work lands, the office is four people, and a privacy control only
  the consultant can operate means private mail sits visible while he's
  found. Same principle as the classifier: a control everybody can inspect
  beats one nobody can. Revisit with SSO.
- **Domain matching is exact**, not suffix: `@paylink.com` does not catch
  `midwestpaylink.com`, and subdomains don't match their parent. Nobody
  should have to reason about accidental catches on a privacy feature.
- **The purge takes whole queue items only.** A private sender's reply
  that had already attached to *someone else's* item as a note is not
  hunted down (notes don't store the author's address). The ingest skip
  runs ahead of the note path, so from the moment an entry exists, no new
  note from that sender can appear.
- The matching convention lives in `app.mail.rules.is_private` (ingest)
  and `app.privacy` (purge); tests in `test_private_senders.py` pin both.

First entry after deploy: `@midwestpaylink.com`.
