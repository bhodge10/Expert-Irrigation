# Phase 1 — what to check by hand

Twenty minutes, and you'll know whether the foundation is right before anything
gets built on top of it.

Start both servers as described in [running-locally.md](running-locally.md),
open <http://localhost:5173>, and work down the list. Sign in as
`craigz@expertsvc.com` / `expert-dev`.

## The queue

- [ ] Signing in with the wrong password says so and doesn't get you in.
- [ ] After signing in you see **10 requests**, counts reading All 10 / Service
      4 / Sales 3 / Other 3.
- [ ] Ron Delaney's "Water running down the driveway" is **at the top** with a
      red **EMERGENCY** tag, above newer messages. Emergencies outrank recency.
- [ ] Sandra Cole's "Deck lights buzzing" shows **amber** confidence bars at
      73%, where everything else is green. That's the deliberately ambiguous
      one — service or sales is a real judgment call, and it should look
      uncertain at a glance.
- [ ] Clicking **Service / Sales / Other** filters the list; the counts don't
      change, because they always describe what's open.
- [ ] **Mine** shows nothing for Craig. Nothing is assigned to him.
- [ ] **Done** shows nothing yet.
- [ ] Reload the page. You're still signed in.

## One message, end to end

Open Sandra Cole's message.

- [ ] The body reads correctly and **"Why it landed here"** lists three plain
      reasons written for the office, not for a developer.
- [ ] **Move queue → Sales.** The card turns blue, the tag says SALES,
      confidence jumps to **100%**, and a toast confirms it.
- [ ] The reasons panel now reads **"Why the sorting first said Service"** and
      adds *"Craig Zumdick moved it to Sales."* This is the point: after a
      human overrules it, the model's reasons are history, and the screen says
      so instead of pretending 100% was its idea.
- [ ] **Assign → Joyce.** The button becomes "Reassign — Joyce" and the card
      shows her purple avatar.
- [ ] **Reply.** The composer says **"sends from megan@expertsvc.com"** — the
      mailbox it arrived at, not yours. That's the customer's view.
- [ ] Type anything and **Send reply**. It moves to a "Replies sent" panel
      stamped *from megan@expertsvc.com · sent by Craig Zumdick* — the customer
      sees Megan, the office sees who really did it.
- [ ] The message leaves the open list. **Done** now shows it, dimmed.
- [ ] Open it from Done and click **Reopen**. It comes back to the open list
      **and the reply is still there.** Handled and replied are separate.

## The part that pays off later

The correction you just made was recorded. Check it:

```
cd backend
.venv\Scripts\python manage.py events
```

- [ ] Ten rows say `(new) -> ... by model` — the original sort of each message.
- [ ] One row says `service -> sales by Craig Zumdick at 73%`.

`manage.py events --corrections-only` shows just the overrides, which is what
you'll actually want once there are a few hundred messages.

That last row is the whole reason the table exists. It captures not just that
Craig disagreed, but that the model was only 73% sure when he did. A pile of
those is what makes the Phase 3 prompt improvable instead of guesswork.

## Empty states and errors

- [ ] **Mine** with nothing assigned reads *"Nothing assigned to you — open any
      message and assign it to yourself to claim it."* An invitation, not an
      apology.
- [ ] Stop the backend (Ctrl-C in terminal 1) and click a queue. You get a
      readable message, not a blank screen or a stack trace. Start it again.

## Production shape

Worth doing once, because it's the only way to catch problems that only appear
in the built version:

```
cd frontend
npm run build

cd ..\backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

- [ ] <http://127.0.0.1:8000> loads the app with no Vite running — FastAPI is
      serving both halves, exactly as Render will.

## Then tell me

Specifically:

1. **Does the sorting match how you'd actually sort it?** The ten samples are
   my guess at your mail. If any of them is in the wrong queue, say which and
   why — that's the raw material for the Phase 3 prompt, and it's much cheaper
   to get right now.
2. **Is anything missing from a message card** that you'd need to triage
   without opening it?
3. **Is "Other" the right name** for reschedules, billing questions and records
   requests? It's the vaguest of the three.

Then we start Phase 2: Azure app registration, the application access policy
that keeps this app locked to five mailboxes, and the poller.
