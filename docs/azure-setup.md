# Connecting to Microsoft 365

This is the part that gets redone in six months by someone who's forgotten it.
Every step says what it's for, so you can tell when something has drifted.

**Read this once before starting.** There's a counterintuitive step — you
deliberately grant the app *no* Graph permissions in Azure — and skipping the
explanation makes it look like a mistake.

Budget 45 minutes the first time.

---

## What you're building

The portal reads mail from three mailboxes and sends replies as them. Rather
than giving it access to the whole tenant and hoping, access is granted through
**Exchange Online RBAC**, which ties three things together:

```
  the app  ──►  a permission  ──►  a set of mailboxes
   (service      ("Application       (a management
    principal)    Mail.ReadWrite")    scope)
```

An app with `Mail.ReadWrite` and no scope can read and delete mail for everyone
in the company. The same app with a scope can only touch the three mailboxes
you named.

### The one thing people get wrong

**Permissions from Entra ID and permissions from Exchange RBAC add together.**

If you consent `Mail.ReadWrite` on the app registration *and* create a scoped
RBAC assignment, you get the union of the two — and the union is unscoped. The
app would have the whole tenant while you believed it had three mailboxes.

This is the mistake a careful person makes by doing both "to be safe."

**So the app registration gets no API permissions at all.** All mail
permissions come from Exchange RBAC, where they arrive with a scope attached.
If you ever open the app registration and see mail permissions listed, remove
them and re-run the verification in Part 5.

---

## Before you start

You need:

- **Application Administrator** (or Cloud Application Administrator) in Entra
  ID — to register the app
- **Exchange Administrator**, and membership of the **Organization Management**
  role group in Exchange Online — to create the RBAC assignment
- The Exchange Online PowerShell module:
  ```powershell
  Install-Module -Name ExchangeOnlineManagement -Scope CurrentUser
  ```

Global Administrator covers all of it if that's simpler.

The three mailboxes:

| Mailbox | Why |
|---|---|
| `craigz@expertsvc.com` | monitored |
| `megank@expertsvc.com` | monitored |
| `joyce@expertsvc.com` | monitored |

> **Reconciled against the tenant 2026-08-15.** Earlier drafts listed
> `megan@` (the address is actually `megank@`), plus `casey@` and `info@`
> (neither exists in the tenant) and a `queue@` forwarding mailbox (never
> created — the forwarding channel is deferred, see decisions.md, and
> `FORWARD_MAILBOX` stays empty in `.env`).

---

## Part 1 — Register the application

1. <https://entra.microsoft.com> → **Applications** → **App registrations** →
   **New registration**
2. Name: `Expert Inbox Queue`
3. Supported account types: **Accounts in this organizational directory only**
4. Redirect URI: **leave blank.** Nobody signs in through this app — it acts on
   its own with a client secret.
5. **Register**

Copy these two from the Overview page into your notes:

| Value | Goes in `.env` as |
|---|---|
| Application (client) ID | `MS_CLIENT_ID` |
| Directory (tenant) ID | `MS_TENANT_ID` |

### Do not add API permissions

There's an **API permissions** page. Skip it. Leave whatever is there by
default (`User.Read` delegated) and add nothing.

This is the step that feels wrong. It isn't — see [The one thing people get
wrong](#the-one-thing-people-get-wrong) above. Permissions come from Part 4.

---

## Part 2 — Create a client secret

1. In the app → **Certificates & secrets** → **Client secrets** → **New client
   secret**
2. Description: `expert-inbox-queue render`
3. Expires: **24 months** (the maximum). Put the expiry date in a calendar now
   — when it lapses, mail ingestion stops silently and the reason will not be
   obvious.
4. **Add**

**Copy the Value immediately.** Not the Secret ID — the **Value** column. It is
shown once and never again; if you navigate away you delete it and start over.

Goes in `.env` as `MS_CLIENT_SECRET`. Never commit it.

---

## Part 3 — Find the service principal IDs

Exchange needs to point at the app, and it wants IDs from the **Enterprise
applications** page — *not* the App registrations page. The pages show
different values under similar names, and using the wrong one produces a
confusing failure in Part 4.

1. Entra ID → **Applications** → **Enterprise applications**
2. Search `Expert Inbox Queue` and open it
3. From the Overview panel:

| Label on the page | You'll use it as |
|---|---|
| **Application ID** | `-AppId` |
| **Object ID** | `-ObjectId` |

They are different values. Write both down.

---

## Part 4 — Grant scoped access in Exchange

```powershell
Connect-ExchangeOnline
```

### 4a. Tell Exchange the app exists

```powershell
New-ServicePrincipal `
  -AppId       "<Application ID from Part 3>" `
  -ObjectId    "<Object ID from Part 3>" `
  -DisplayName "Expert Inbox Queue"
```

This creates a pointer, not a new identity. Delete the app in Entra and this
disappears with it.

### 4b. Define which mailboxes are in scope

We scope by membership of a **mail-enabled security group**, so adding a
mailbox later is a group membership change, not a cmdlet.

The group: `Service_and_sales_queue@expertsvc.com`. Every monitored mailbox
must be a **direct** member — and *only* the monitored mailboxes: membership
IS the scope, so anyone else in the group is mail the app can read. (Found the
hard way 2026-08-15 — the group had accumulated five extra members that had to
be pruned.) Note `MemberOfGroup` does not evaluate nested groups, so a
group inside the group silently drops its mailboxes from scope. — `MemberOfGroup` does not evaluate nested groups, so a
group inside the group silently drops its mailboxes from scope.

The filter wants the group's distinguished name, not its email address:

```powershell
Get-Group -Identity "Service_and_sales_queue@expertsvc.com" | Format-List Name,DistinguishedName
```

```powershell
New-ManagementScope `
  -Name "Expert Inbox Queue Mailboxes" `
  -RecipientRestrictionFilter "MemberOfGroup -eq '<full DN from Get-Group>'"
```

Keep the DN inside the single quotes — DNs contain commas.

(`New-` creates, `Set-ManagementScope` edits one that already exists. Running
`Set-` first fails with "couldn't be found".)

> The other way is an explicit list, no group involved:
>
> ```powershell
> New-ManagementScope `
>   -Name "Expert Inbox Queue Mailboxes" `
>   -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'craigz@expertsvc.com' -or PrimarySmtpAddress -eq 'megank@expertsvc.com' -or PrimarySmtpAddress -eq 'joyce@expertsvc.com'"
> ```
>
> Verbose but self-explanatory a year later. Whichever you use, Part 5 is what
> proves the scope actually contains what you think it does — with a group,
> an empty or mis-membered group fails silently until then.

### 4c. Grant the permission, scoped

The rollout is staged. **Stage one is read-only** — the app can ingest mail
into the queue but cannot send, modify, or tag anything. Sending and Outlook
tagging come later, once the queue has earned some trust
(see [decisions.md](decisions.md)).

**Stage one — now:**

```powershell
New-ManagementRoleAssignment `
  -App "<Application ID>" `
  -Role "Application Mail.Read" `
  -CustomResourceScope "Expert Inbox Queue Mailboxes"
```

While read-only, `OUTLOOK_CATEGORY` must stay **empty** in `.env` — that's the
switch that stops the app attempting category writes it has no permission for.
Replying from the portal will fail with a clear error and record nothing;
that's expected until stage two.

**Stage two — when ready to send and tag:**

```powershell
New-ManagementRoleAssignment `
  -App "<Application ID>" `
  -Role "Application Mail.ReadWrite" `
  -CustomResourceScope "Expert Inbox Queue Mailboxes"

New-ManagementRoleAssignment `
  -App "<Application ID>" `
  -Role "Application Mail.Send" `
  -CustomResourceScope "Expert Inbox Queue Mailboxes"

# ReadWrite contains Read; drop the now-redundant grant.
Get-ManagementRoleAssignment -App "<Application ID>" |
  Where-Object Role -eq "Application Mail.Read" |
  Remove-ManagementRoleAssignment
```

Then do Part 6 (categories) and set `OUTLOOK_CATEGORY` in `.env`.

What each role buys:

| Role | Needed for |
|---|---|
| `Application Mail.Read` | Ingesting mail into the queue |
| `Application Mail.ReadWrite` | The above, **plus** writing the `Expert Queue` category onto it |
| `Application Mail.Send` | Sending replies as the mailbox they arrived at |

> There's a bundled `Application Mail Full Access` role. Explicit assignments
> make the intent legible and let you revoke pieces separately.

---

## Part 5 — Prove it's actually locked down

This is the part worth doing properly. Everything above can look right and be
wrong.

```powershell
# A mailbox that SHOULD be reachable
Test-ServicePrincipalAuthorization -Identity "<Application ID>" -Resource "craigz@expertsvc.com" | Format-Table

# A mailbox that should NOT be
Test-ServicePrincipalAuthorization -Identity "<Application ID>" -Resource "<any other mailbox in the company>" | Format-Table
```

Read the **InScope** column:

| Mailbox | Expected |
|---|---|
| The three above | `True` |
| Anyone else | `False` |

A quick loop for the positive side:

```powershell
"craigz","megank","joyce" | ForEach-Object {
  Test-ServicePrincipalAuthorization -Identity "<Application ID>" -Resource "$_@expertsvc.com"
} | Format-Table Identity,InScope
```

Note the errors it can throw: `Couldn't find object` means the address doesn't
resolve to any recipient in the tenant at all — a typo or a mailbox that
doesn't exist — which is a different failure from `InScope False`.

**If an out-of-scope mailbox comes back `True`**, the app has an unscoped grant
somewhere. Almost always this means mail permissions were consented on the app
registration. Go back to Part 1, remove them from **API permissions**, and test
again.

`Test-ServicePrincipalAuthorization` deliberately bypasses the permission cache
so it tells you the truth immediately. Real API calls do not — see
[Troubleshooting](#troubleshooting).

---

## Part 6 — Create the Outlook category

**Skip this while running read-only (stage one of Part 4c).** Tagging needs
`Application Mail.ReadWrite`, and `OUTLOOK_CATEGORY` stays empty in `.env`
until that's granted.

The app writes a category named `Expert Queue` onto mail it has picked up. The
*colour* comes from each mailbox's own category list, so the category has to
exist there or the label shows up grey.

Creating it via the API would need a third permission (`MailboxSettings.ReadWrite`)
for something you do once. Do it by hand instead — about two minutes.

In Outlook, **for each of the three mailboxes**:

1. Right-click any message → **Categorize** → **All Categories**
2. **New** → name it exactly `Expert Queue` → pick a colour (green matches the
   portal) → **OK**
3. **New** again → `Expert Queue — Handled` → a second colour (grey works) →
   **OK**

The name must match exactly, em dash and all. Copy-paste it rather than typing.

---

## Part 7 — Fill in `.env`

```
MS_TENANT_ID=<Directory (tenant) ID from Part 1>
MS_CLIENT_ID=<Application (client) ID from Part 1>
MS_CLIENT_SECRET=<the Value from Part 2>
MONITORED_MAILBOXES=craigz@expertsvc.com,megank@expertsvc.com,joyce@expertsvc.com
FORWARD_MAILBOX=
```

`FORWARD_MAILBOX` stays empty: the `queue@` staff-forwarding mailbox was
deferred on 2026-08-15 (it was never created — see decisions.md). If it's
revived later, create the mailbox, add it to the scoping group as a direct
member, and set `FORWARD_MAILBOX=queue@expertsvc.com` — mail arriving there is
parsed as a forward to recover the original sender.

On Render these go in the environment group, never in a file.

Then prove it from the app's side:

```powershell
cd backend
python manage.py checkgraph
```

It fetches a token and reads the newest message from each mailbox — nothing
is written or sent. Every line should say `ok`. A `DENIED` on a mailbox that
Part 5 said was in scope is almost always the permission cache — wait and
re-run before changing anything.

---

## Troubleshooting

**Permission changes take 30 minutes to 2 hours to take effect.** Exchange
caches an app's permissions; an idle app's cache resets after 30 minutes, an
active one is held up to 2 hours. So: you fix a scope, test it, see the old
behaviour, and conclude you did it wrong.

`Test-ServicePrincipalAuthorization` bypasses the cache. **Trust it over a live
API call.** If the cmdlet says `InScope: True` and a real call still 403s, wait
and try again before changing anything.

---

**403 on every mailbox, including in-scope ones.** Either the cache (above), or
the RBAC assignment didn't land. Check:

```powershell
Get-ManagementRoleAssignment -App "<Application ID>" | Format-Table Name,Role,CustomResourceScope
```

You should see one row per granted role — just `Application Mail.Read` while
running read-only, `Mail.ReadWrite` and `Mail.Send` after stage two — every
one with `Expert Inbox Queue Mailboxes` in `CustomResourceScope`. A blank
scope means the app has unscoped access — fix that immediately, it's the
thing this whole document exists to prevent.

---

**`New-ManagementRoleAssignment` says "You don't have access to create,
change, or remove … you must be assigned a delegating role assignment".**
Your admin account isn't an *explicit* member of the **Organization
Management** role group. Global Admin / Exchange Administrator in Entra maps
into Exchange implicitly, and that implicit membership does not pass this
check. Add the account explicitly (Exchange admin center → **Roles** →
**Admin roles** → **Organization Management** → **Assigned** → **Add**, or
`Add-RoleGroupMember -Identity "Organization Management" -Member <upn>`),
then `Disconnect-ExchangeOnline` and reconnect — membership is evaluated when
the session starts.

---

**`New-ServicePrincipal` says the object doesn't exist.** You used IDs from the
App registrations page. Get them from **Enterprise applications** instead —
Part 3.

---

**Everything worked, then stopped months later.** The client secret expired.
That's Part 2. Create a new one, update `MS_CLIENT_SECRET`, restart the worker.
Nothing else needs redoing — the Exchange RBAC side is tied to the app, not the
secret.

---

**Out-of-scope mailbox tests `True`.** Mail permissions are consented on the
app registration. Remove them (Part 1) and re-test. See [The one thing people
get wrong](#the-one-thing-people-get-wrong).

---

## Undoing all of it

```powershell
Get-ManagementRoleAssignment -App "<Application ID>" | Remove-ManagementRoleAssignment
Remove-ManagementScope -Identity "Expert Inbox Queue Mailboxes"
Remove-ServicePrincipal -Identity "<Application ID>"
```

Then delete the app registration in Entra. Deleting the app registration alone
also removes the Exchange side automatically, but doing it in this order leaves
less behind to wonder about.
