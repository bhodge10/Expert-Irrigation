# Expert Inbox Queue

A shared queue for customer email at **Expert Irrigation & Outdoor Lighting**
(Hebron, KY).

Customer mail lands in individual Outlook inboxes today, and Craig reads each
one and forwards it to the right person. This portal removes that middle step:
mail is read from Microsoft 365, sorted into **Service / Sales / Other**, and
dropped into a queue the office works from — reply, assign, correct the
sorting, mark it handled, without opening Outlook.

The one-sentence goal: **the owner stops being a router.**

## Where the project is

| Phase | What it is | Status |
|---|---|---|
| 1 | Portal shell running on seeded data | **Done** |
| 2 | Microsoft Graph ingestion | Not started |
| 3 | Classification and drafted replies | Not started |
| 4 | ServiceTitan lookup and write-back | Not started |

Phase 1 has no Microsoft connection and no AI. The queue, the login, the
assign/move/handle/reply actions and the whole interface are real and running
against ten sample messages.

**Nothing sends email in Phase 1.** Writing a reply saves it against the
message and marks it handled. That's the whole behavior.

## Start here

- **[docs/running-locally.md](docs/running-locally.md)** — setup and everyday commands
- **[docs/adding-a-user.md](docs/adding-a-user.md)** — office users
- **[docs/phase-1-check.md](docs/phase-1-check.md)** — what to click to satisfy yourself it works
- **[docs/azure-setup.md](docs/azure-setup.md)** — connecting to Microsoft 365 (do this before Phase 2 code)
- **[docs/decisions.md](docs/decisions.md)** — choices already argued, and why

## How it's put together

```
backend/          FastAPI + SQLAlchemy. SQLite locally, Postgres on Render.
  app/
    models.py     The five tables. Start here to understand the data.
    routers/      One file per group of endpoints.
    seed_data.py  The sample office and mail.
  alembic/        Schema migrations.
  manage.py       seed / adduser / passwd / users.
frontend/         React + Vite, plain CSS. No component library.
docs/             Anything you'd otherwise have to rediscover.
render.yaml       The production setup, as code.
```

The frontend is built into `frontend/dist` and served by FastAPI in production,
so Render runs one web service rather than two.

### The data

Five tables (`backend/app/models.py`):

- **users** — the five office people
- **messages** — one row per inbound customer email
- **replies** — one row per reply a human sent, including who sent it
- **classification_events** — every automatic sort and every human correction
- **sessions** — logged-in browsers

`classification_events` matters more than it looks. It's the record of what the
sorting gets wrong, and it's what makes the prompt improvable in Phase 3. Every
queue change writes one — the automatic call with no user attached, the human
correction with one.

### Behavior worth knowing

- **A reply goes out from the mailbox it arrived at.** Mail to `craigz@` is
  answered as Craig even when Joyce clicks Send. The customer never sees the
  machinery; the message records who actually sent it.
- **Assignment is a signal, not a lock.** Anyone can act on anything. Five
  people, no permission model.
- **Handled is separate from replied.** Some messages get worked without a
  reply. Sending one marks it handled by default, and anything can be reopened.
- **Correcting the sorting sets confidence to 100 and logs the correction.**
  After that the detail pane presents the model's reasons as history — what it
  first thought and who overruled it — instead of as the current call.

## API

Everything except `/api/health` and `/api/auth/login` needs a session cookie.

| Method | Path | |
|---|---|---|
| POST | `/api/auth/login` | email + password, sets the cookie |
| POST | `/api/auth/logout` | |
| GET | `/api/auth/me` | current user |
| GET | `/api/users` | the roster, for the assign menu |
| GET | `/api/messages?queue=&scope=` | `queue`: all/service/sales/other · `scope`: open/mine/done. Returns messages plus open counts. |
| GET | `/api/messages/{id}` | full message, reply history, correction history |
| POST | `/api/messages/{id}/assign` | `{assignee_id}` — null clears it |
| POST | `/api/messages/{id}/queue` | `{queue}` — logs a classification event |
| POST | `/api/messages/{id}/status` | `{status}` — open or handled |
| POST | `/api/messages/{id}/reply` | `{body_text, mark_handled}` |

Interactive docs at `/docs` while the server is running.

## Secrets

`.env` is gitignored and must stay that way. `.env.example` lists every
variable with empty values. Real values live in Render's environment group.

## Working on this

- Boring and readable beats clever. This gets edited at 10pm.
- Ask before adding a dependency that isn't obviously necessary.
- Anything you had to figure out once goes in `docs/` so you don't figure it
  out twice.
