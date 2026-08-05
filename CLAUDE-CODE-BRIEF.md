# Project brief — Expert Inbox Queue

Paste this whole file into Claude Code as your first message. Work through it in phases; don't build everything at once.

---

## What we're building

A web portal for **Expert Irrigation & Outdoor Lighting** (Hebron, KY — irrigation and landscape lighting contractor, ~5 office users). Customer emails currently land in individual Outlook inboxes and the owner manually reads and forwards each one to the right person. This portal removes that middle step.

Incoming mail is read from Microsoft 365, classified into **Service / Sales / Other**, and dropped into a shared queue the office team works from. They can read it, reply to the customer, assign it to a teammate, correct a wrong classification, and mark it handled — without opening Outlook.

**The one-sentence goal:** the owner stops being a router.

## Users

| Key | Name | Role |
|---|---|---|
| `craig` | Craig Zumdick | Owner |
| `megan` | Megan | Office |
| `joyce` | Joyce | Service scheduling |
| `casey` | Casey | Office |
| `jordan` | Jordan | Sales / estimating |

Monitored mailboxes: the individual addresses above plus `info@expertsvc.com`. Website form submissions also arrive as email and should be parsed like anything else.

## Stack

- **Backend:** Python + FastAPI. SQLite for local dev, Postgres in production.
- **Frontend:** React + Vite, plain CSS (no component library). A working static mockup is attached — match its layout and visual language.
- **Mail:** Microsoft Graph API, app-only auth (client credentials), `Mail.Read` and `Mail.Send` scoped to the specific mailboxes above via an application access policy.
- **Classification:** Anthropic API, `claude-sonnet-4-6`.
- **Hosting:** Render — one web service, one Postgres instance, one background worker. Use `render.yaml` for infra-as-code from day one.
- **Later:** ServiceTitan API for contact and job lookup. Design for it now, build it in Phase 4.

Keep dependencies minimal. This is maintained by one person who is learning as he goes.

---

## Data model

**`messages`** — one row per inbound email
`id`, `graph_message_id` (unique), `conversation_id`, `mailbox`, `from_name`, `from_email`, `subject`, `body_text`, `body_html`, `received_at`, `queue` (service|sales|other), `confidence` (0–100), `is_urgent`, `classification_reasons` (JSON array of short strings), `assignee_id` (nullable), `status` (open|handled), `handled_at`, `handled_by`, `created_at`

**`users`** — `id`, `email`, `display_name`, `initials`, `color`, `role`, `password_hash`, `is_active`

**`replies`** — `id`, `message_id`, `user_id`, `body_text`, `sent_at`, `graph_sent_id`

**`classification_events`** — every automatic classification and every human correction: `id`, `message_id`, `from_queue`, `to_queue`, `changed_by` (nullable = the model), `confidence`, `created_at`

That last table matters more than it looks. It's the record of what the model gets wrong, and it's what makes the prompt improvable later. Don't skip it.

---

## Phases

### Phase 1 — Portal shell with seeded data
No Microsoft connection yet. Get the UI real against fixture data.

- FastAPI app, SQLite, the models above, Alembic migrations
- Seed script with ~10 realistic messages (borrow from the attached mockup)
- React frontend matching the mockup: queue rail with counts, Open/Mine/Done filter, message cards, detail pane, reply composer, assign menu, move-queue menu
- Session auth — email and password, server-side sessions, bcrypt. No SSO yet.
- `GET /api/messages?queue=&scope=`, `GET /api/messages/{id}`, `POST /api/messages/{id}/assign`, `POST /api/messages/{id}/queue`, `POST /api/messages/{id}/status`, `POST /api/messages/{id}/reply`

Reply in this phase writes a `replies` row and marks the message handled. It does not send anything.

### Phase 2 — Microsoft Graph ingestion
- Azure app registration: app-only permissions `Mail.Read`, `Mail.Send`, `User.Read.All`. Document the exact steps in `docs/azure-setup.md` — this is the part that will be re-done six months from now by someone who forgot.
- **Restrict access with an application access policy** (`New-ApplicationAccessPolicy` in Exchange Online PowerShell) so the app can only touch the five mailboxes listed above, not the whole tenant. Do this before the first real token.
- Background poller every 60s per mailbox using delta queries. Store the delta token so restarts don't re-ingest.
- Dedupe on `graph_message_id`. A message sent to two monitored mailboxes should create one row, not two.
- Skip: internal senders (`@expertsvc.com`), automated no-reply addresses, and anything already in a `conversation_id` we've seen — replies thread onto the existing message rather than creating new queue items.

### Phase 3 — Classification and drafted replies
Two separate Anthropic calls, run on ingest.

**Classify** — returns strict JSON, no prose, no markdown fences:
```json
{"queue":"service","confidence":91,"is_urgent":false,"reasons":["...","...","..."]}
```
Rules to encode in the system prompt:
- **Service** — something already installed is broken or needs maintenance. Repairs, leaks, dead zones, startups, winterization, backflow tests, lights out.
- **Sales** — new work. New installs, quotes, additions, membership signups, builder bids, anything from a customer with no account.
- **Other** — no work to dispatch. Reschedules, billing questions, records requests, vendor mail, general questions.
- **Urgent** when there's active water loss, property damage, or an explicit same-day request. Urgency is independent of queue.
- Ambiguity is real and should show up as low confidence, not a coin flip. "My four-year-old transformer is humming and half the run is out, is it time to replace it?" is genuinely between service and sales.
- `reasons` are three short factual observations that justify the call — written for the office staff, not for a developer.

**Draft a reply** — plain text, in Craig's voice. Feed the last ~50 sent replies from his mailbox as tone examples. His register: direct, a bit of plain technical explanation of what's probably wrong, no corporate padding, signs off with name / company / (859) 282-8101. Never promises a specific appointment time — that's the human's job.

Store `confidence` and surface it in the UI. When a user moves a message to a different queue, log it to `classification_events` and set confidence to 100.

**Guardrail: nothing sends automatically.** Every reply passes through a human clicking Send. Revisit only after months of watching what the drafts actually look like.

### Phase 4 — ServiceTitan
- Match `from_email` and any phone number in the body against ServiceTitan customers; show account, membership tier and open jobs in the detail pane
- Push new sales contacts into the CRM
- Link reschedule requests to the existing job

Check what their API plan actually allows before building against it.

---

## Behavior details worth getting right

- **Reply sends from the mailbox it arrived at**, so the customer never sees the machinery. A message to `craigz@` replies as Craig even when Joyce clicks send — with an internal note on the message recording who actually sent it.
- **Assignment doesn't own the message.** Anyone can act on anything; assignment is a signal, not a lock. Small office, no permission model needed.
- **Handled is separate from replied.** Some messages get assigned and worked without a reply. Sending a reply marks handled by default, but a user can reopen.
- **New-message notification** — a badge on the queue counts plus optional browser notification for urgent items. Craig gets a text or push for urgent only. Don't build an alert for everything; it becomes noise instantly, which is the problem we're solving.
- Empty states are invitations, not apologies. Errors say what happened and what to do.

## Environment

```
DATABASE_URL=
SESSION_SECRET=
MS_TENANT_ID=
MS_CLIENT_ID=
MS_CLIENT_SECRET=
MONITORED_MAILBOXES=craigz@expertsvc.com,megan@...,joyce@...,casey@...,info@...
ANTHROPIC_API_KEY=
SERVICETITAN_CLIENT_ID=      # phase 4
SERVICETITAN_CLIENT_SECRET=
SERVICETITAN_TENANT_ID=
SERVICETITAN_APP_KEY=
```

Never commit secrets. `.env.example` with empty values, real values in Render's environment group.

---

## How to work with me on this

- Start with Phase 1 only. Show me a running portal against seeded data before touching Microsoft.
- After each phase, stop and tell me what to verify by hand.
- Prefer boring, readable code over clever code. I'll be the one editing this at 10pm.
- Write down anything I'll need to remember — Azure steps, Render config, how to add a user — in `docs/`.
- If the classification prompt needs tuning, treat it as a file (`prompts/classify.md`) I can edit without touching Python.
- Ask me before adding a dependency that isn't obviously necessary.
