# Deploying to Render — the production blueprint

This applies `render.yaml`: a web service (the portal), a worker (the mail
poller + classifier), and a Postgres 16 database. Roughly $20/month across
the three. The old free-plan Docker demo service is separate — delete it
once this is live.

Nothing migrates from the laptop's SQLite: the worker re-ingests the last 7
days fresh on Postgres, re-classifies (~$1 of API spend), and re-drafts.
Users are created by hand (step 4) — they don't carry over either.

## 1. Apply the blueprint

Render dashboard → **New +** → **Blueprint** → connect the
`bhodge10/Expert-Irrigation` GitHub repo → it reads `render.yaml` → **Apply**.

## 2. Fill the secrets when prompted

The blueprint creates an env group `expert-inbox-secrets` and asks for four
values (same ones as the local `.env`):

| Key | Where it comes from |
|---|---|
| `MS_TENANT_ID` | Entra → app registration → Overview → Directory (tenant) ID |
| `MS_CLIENT_ID` | Same page → Application (client) ID |
| `MS_CLIENT_SECRET` | Prefer a **second** client secret created just for Render (Certificates & secrets → New) so laptop and production are separately revocable |
| `ANTHROPIC_API_KEY` | console.anthropic.com — again, a second key named "render" keeps them separable |

Everything else (mailboxes, model, empty category vars) is already in the
blueprint with the right values.

## 3. Wait for the first deploy

Web service goes green when `/api/health` answers. The worker's logs should
show `first sync — N message(s) from the last 7 day(s)` per mailbox, then
quiet 60-second cycles. If mailboxes come back DENIED, it's the Graph
permission cache — see azure-setup.md Troubleshooting.

## 4. Create the logins

Web service → **Shell**:

```
cd backend
python manage.py adduser --email craigz@expertsvc.com --name "Craig Zumdick" --initials CZ --role Owner
python manage.py adduser --email megank@expertsvc.com --name "Megan" --initials M --role Office
python manage.py adduser --email joyce@expertsvc.com --name "Joyce Saltzsieder" --initials JS --role "Service scheduling"
```

Each prompts for a password. `docs/adding-a-user.md` has the details.

## 5. Point people at it

The portal is `https://expert-inbox-queue.onrender.com` (or attach a custom
domain on the web service → Settings → Custom Domains).

## Afterwards

- Delete the old free demo service so nobody bookmarks stale data.
- The laptop's worker and server can stop for good — if both run at once,
  mail gets ingested twice (into two different databases, so nothing
  breaks, but the laptop one is now pointless).
- Prompt edits still work the same way: edit `backend/prompts/*.md`, commit,
  push — Render redeploys automatically on push to main.
