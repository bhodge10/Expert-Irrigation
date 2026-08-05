# Adding, changing, and removing office users

There's no admin screen. Users are added from the command line, which is the
right trade for an office of five — one less thing to build and secure.

## Add someone

From `backend/`:

```
.venv\Scripts\python manage.py adduser
```

It asks for six things:

| Field | What it's for | Example |
|---|---|---|
| Email | How they sign in. Also the mailbox we monitor for them, if they have one. | `casey@expertsvc.com` |
| Display name | Shown on cards and in the assign menu | `Casey` |
| Initials | The 1–3 letters in their avatar circle | `C` |
| Avatar color | Hex color for that circle | `#B96C0C` |
| Role | Shown next to their name in the assign menu | `Office` |
| Password | What they type to sign in | |

Or pass it all as flags, which is easier to get right:

```
.venv\Scripts\python manage.py adduser ^
  --email casey@expertsvc.com ^
  --name Casey ^
  --initials C ^
  --color "#B96C0C" ^
  --role Office ^
  --password "something-they-will-change"
```

Colors already in use, so you can pick one that doesn't collide:

| Person | Color |
|---|---|
| Craig | `#1F7A47` green |
| Megan | `#1D6E9C` blue |
| Joyce | `#7A4FA3` purple |
| Casey | `#B96C0C` amber |
| Jordan | `#A9342A` red |

## Change a password

```
.venv\Scripts\python manage.py passwd megan@expertsvc.com
```

It prompts, and what you type isn't echoed. Passwords are stored as bcrypt
hashes — nobody, including you, can read an existing one. Resetting is the only
option if someone forgets.

## See who's set up

```
.venv\Scripts\python manage.py users
```

## Remove someone

```
.venv\Scripts\python manage.py deactivate casey@expertsvc.com
```

This deactivates rather than deletes, on purpose. A deactivated user can't sign
in, is signed out of any browser they left open, and disappears from the assign
menu — but the messages they handled and the replies they sent still show their
name. Deleting the row would blank all of that out, and you'd lose the record of
who did what.

If they come back:

```
.venv\Scripts\python manage.py deactivate casey@expertsvc.com --reactivate
```

Their old password still works, since it was never touched.

## On production

Same commands, run in a Render shell on the web service, from the `backend`
directory. Render's Python is already on the path there, so drop the
`.venv\Scripts` prefix:

```
cd backend
python manage.py adduser
```

## Two things worth knowing

**Adding a user here does not start monitoring their mailbox.** That's a
separate list — `MONITORED_MAILBOXES` in the environment — plus the Azure
application access policy from Phase 2. A person can use the portal without
having a monitored mailbox (Jordan does), and a mailbox can be monitored
without belonging to a portal user (`info@` is).

**Never run `manage.py seed` against production.** It inserts ten fake customer
emails. It won't touch existing users, but you'd be explaining fictional
sprinkler emergencies to Craig.
