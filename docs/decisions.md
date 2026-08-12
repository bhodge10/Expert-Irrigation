# Decisions

Choices that were argued once and shouldn't be re-argued from scratch. If you
change one, edit the entry and say why — a decision with a stale reason is
worse than no record.

---

## Render runs a Dockerfile, and render.yaml does not describe production

**Decided:** 2026-08-12 · **Phase:** 1

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
it can modify and delete mail in the five scoped mailboxes, not just read it.
That's a real increase in what a leaked client secret would allow. Accepted
because the Exchange RBAC scope (below) contains it to five mailboxes, and
because rotating the secret is cheap.

**Deliberately not doing:** granting `MailboxSettings.ReadWrite` so the app can
create the colored category itself. That's a third permission for a task you do
once. Create the category by hand in each mailbox instead — see
[azure-setup.md](azure-setup.md).

**Revisit when:** Craig stops looking at Outlook. At that point the tags are
decoration and dropping back to `Mail.Read` is a real security improvement.

---

## Two ways in for mail that misses the queue

**Decided:** 2026-08-01 · **Phase:** 2

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

## The sorting learns from corrections, but nothing tunes itself silently

**Decided:** 2026-08-01 · **Phase:** 3

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
