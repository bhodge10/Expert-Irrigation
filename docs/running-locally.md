# Running it on your machine

You need Python 3.11+ and Node 20+. Check with `python --version` and `node --version`.

Everything below is run from the repo root unless it says otherwise.

## First time

**1. Make a `.env`**

```
copy .env.example .env
```

Then generate a session secret and paste it in as `SESSION_SECRET`:

```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Leave `DATABASE_URL` empty. Empty means "use the SQLite file at
`backend/expert_inbox.db`", which is what you want locally. Everything else in
that file is for later phases.

**2. Set up the backend**

```
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\alembic upgrade head
.venv\Scripts\python manage.py seed
```

`seed` creates the five office users and ten sample messages. It prints the
password it used — `expert-dev` unless you pass `--password`.

**3. Set up the frontend**

```
cd ..\frontend
npm install
```

## Every time after that

Two terminals.

**Terminal 1 — the API:**

```
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — the app:**

```
cd frontend
npm run dev
```

Open <http://localhost:5173>. Sign in as `craigz@expertsvc.com` / `expert-dev`.

Vite forwards `/api` to port 8000, so the browser sees one origin and the login
cookie just works. Both halves reload when you save a file.

## Seeing it the way Render will

Render runs one service: FastAPI serves the API *and* the built frontend. To
reproduce that locally:

```
cd frontend
npm run build

cd ..\backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Then open <http://127.0.0.1:8000> — no Vite involved. Worth doing before you
push anything you care about, because it's the only way to catch a problem that
only shows up in the built version.

FastAPI only serves the frontend if `frontend/dist` exists. In dev it doesn't,
so this stays out of your way.

## Useful commands

Run these from `backend/` with `.venv\Scripts\python` in front:

| Command | What it does |
|---|---|
| `manage.py users` | List who can sign in |
| `manage.py seed` | Add users and messages if they're missing |
| `manage.py seed --reset` | Reload the sample messages from scratch (keeps users) |
| `manage.py adduser` | Add an office user — see [adding-a-user.md](adding-a-user.md) |
| `manage.py passwd EMAIL` | Change someone's password |
| `manage.py deactivate EMAIL` | Stop a login without losing their history |
| `manage.py events` | What the sorting called, and who corrected it |

And Alembic, also from `backend/`:

| Command | What it does |
|---|---|
| `.venv\Scripts\alembic upgrade head` | Apply migrations |
| `.venv\Scripts\alembic revision --autogenerate -m "what changed"` | Create one after editing `app/models.py` |
| `.venv\Scripts\alembic downgrade -1` | Undo the last migration |

**Always read a generated migration before applying it.** Autogenerate is good,
not perfect — it misses renames and reads them as a drop plus an add, which
throws the data away.

## When something's wrong

**"No such table" —** you skipped `alembic upgrade head`.

**Login says the password doesn't match —** check the account exists with
`manage.py users`, then reset it with `manage.py passwd craigz@expertsvc.com`.

**The list is empty and the counts are zero —** nothing is seeded. Run
`manage.py seed`.

**Port 8000 is busy —** something else is on it, probably a uvicorn you forgot
about. Find it with `netstat -ano | findstr :8000` and stop that process ID.

**You want to start completely over —** delete `backend/expert_inbox.db`, then
run `alembic upgrade head` and `manage.py seed` again. That file is the entire
local database; nothing else is lost.

## The API, by hand

Interactive docs are at <http://127.0.0.1:8000/docs> while the server is
running. Everything except `/api/health` and `/api/auth/login` needs a session
cookie, so sign in through that page first (or use the app in another tab —
same cookie).
