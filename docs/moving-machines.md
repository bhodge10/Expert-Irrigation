# Moving to another machine

Written **2026-08-12**, moving off the original dev box.

`git clone` brings the code and nothing else. The three things that matter —
customer mail samples, the Azure secrets, and the Render dashboard config —
all live outside the repo on purpose. This is the list of what to carry.

## 1. Carry these by hand — a clone will not bring them

| Path | Size | What to do |
|---|---|---|
| `docs/email examples/` | 12.2 MB | **Copy from the old machine.** |
| `docs/Simple IT email examples from Craig.zip` | 11.4 MB | **Copy from the old machine.** |
| `backend/expert_inbox.db` | 0.1 MB | Don't bother — recreate it (step 3). |
| `.venv/`, `node_modules/`, `frontend/dist/`, `__pycache__/` | — | Don't bother — rebuilt by setup. |
| `.env` | — | Doesn't exist on the old machine. Create from `.env.example`. |

Both customer-mail items are **real names, addresses and phone numbers**.
They're gitignored precisely so they never leave a machine you control. Move
them on a USB stick or a direct copy between the two computers — not through
email, not by pasting into a cloud drive or a chat window. If you'd rather not
move them at all, ask Craig to re-send; that's a legitimate option and costs
one email.

The `.zip` and the unpacked `docs/email examples/` folder are two copies of the
same material. Carrying just the zip is enough.

## 2. Not on any machine — from your own notes

The Azure app registration **Application ID, Directory (tenant) ID, and client
secret**. `setup-progress.md` records these as "in Brad's notes, never in this
repo," and that hasn't changed. Without them `manage.py checkgraph` and the
worker can't authenticate. If the secret has gone missing, generate a new one
in the app registration — cheap, and `azure-setup.md` Part 2 covers it.

## 3. On the new machine

```
git clone https://github.com/bhodge10/Expert-Irrigation.git
cd Expert-Irrigation
git config user.name "Brad Hodge"
git config user.email "brad.hodge@simple-it.us"
```

Then follow [running-locally.md](running-locally.md) — "First time" — which
covers the `.env`, the venv, migrations, seeding, and npm. Nothing about it
changes on a new box. You'll need Python 3.11+ and Node 20+ installed first.

Sign in locally as `craigz@expertsvc.com` / `expert-dev` once seeded.

## 4. Where the work stands

**Azure / Microsoft 365 —** see [setup-progress.md](setup-progress.md). Resume
at **Part 4c stage one**, blocked on your admin account needing explicit
membership in the Organization Management role group. That file has the resume
commands and is the authority; nothing here supersedes it.

**Render deployment —** see below.

**Repo —** `main`, four commits, pushed and clean at the time of writing:

```
7499a84  Add checkgraph command and record the staged read-only Graph rollout
4e960df  Bootstrap an admin user at container startup
16afe6b  Add Dockerfile so Render can build the service
8405537  Initial commit
```

## 5. The Render service

Live config, none of which is in the repo:

| | |
|---|---|
| Service | `Expert-Irrigation` (`srv-d9n08qp42hec73el6io0`) |
| URL | https://expert-irrigation.onrender.com |
| Type / plan | Docker, Free |
| Deploys from | `bhodge10/Expert-Irrigation`, branch `main`, auto-deploy on push |

**Environment variables that must be set in the dashboard.** The service builds
and serves without them; you just can't log in, and the session cookie is
signed with a known-insecure default.

| Key | Why |
|---|---|
| `ADMIN_EMAIL` | Creates the only account. Without it, no login exists. |
| `ADMIN_PASSWORD` | Same. |
| `SESSION_SECRET` | Otherwise `config.py` falls back to `dev-only-insecure-secret`. |
| `COOKIE_SECURE` | `1` — Render terminates TLS, so the cookie should be Secure. |

Optional: `ADMIN_NAME`, `ADMIN_INITIALS`, `ADMIN_COLOR`, `ADMIN_ROLE`.

**Two things to know before you trust it.**

The free instance has **no persistent database**. With `DATABASE_URL` unset the
app falls back to SQLite inside the container, which is wiped on every deploy
and every idle spin-down. The admin account comes back each start because the
entrypoint recreates it from the env vars — but messages, replies and
assignments made through the UI do not. Treat the deployed site as a demo until
it's on Postgres.

Free tier also has **no shell**, which is why the admin bootstrap lives in
`docker-entrypoint.sh` at all. On a paid instance, prefer the documented path
in [adding-a-user.md](adding-a-user.md) and drop the `ADMIN_*` variables.

## 6. Once the move is done

Delete this file. `running-locally.md`, `azure-setup.md` and `decisions.md` are
the permanent records; this one is scaffolding for a single afternoon.
