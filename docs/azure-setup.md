# Connecting to Microsoft 365

This is the part that gets redone in six months by someone who's forgotten it.
Every step says what it's for, so you can tell when something has drifted.

**Read this once before starting.** There's a counterintuitive step — you
deliberately grant the app *no* Graph permissions in Azure — and skipping the
explanation makes it look like a mistake.

Budget 45 minutes the first time.

---

## What you're building

The portal reads mail from five mailboxes and sends replies as them. Rather
than giving it access to the whole tenant and hoping, access is granted through
**Exchange Online RBAC**, which ties three things together:

```
  the app  ──►  a permission  ──►  a set of mailboxes
   (service      ("Application       (a management
    principal)    Mail.ReadWrite")    scope)
```

An app with `Mail.ReadWrite` and no scope can read and delete mail for everyone
in the company. The same app with a scope can only touch the five mailboxes you
named.

### The one thing people get wrong

**Permissions from Entra ID and permissions from Exchange RBAC add together.**

If you consent `Mail.ReadWrite` on the app registration *and* create a scoped
RBAC assignment, you get the union of the two — and the union is unscoped. The
app would have the whole tenant while you believed it had five mailboxes.

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

The five mailboxes, plus the forwarding address:

| Mailbox | Why |
|---|---|
| `craigz@expertsvc.com` | monitored |
| `megan@expertsvc.com` | monitored |
| `joyce@expertsvc.com` | monitored |
| `casey@expertsvc.com` | monitored |
| `info@expertsvc.com` | monitored |
| `queue@expertsvc.com` | staff forward strays here — create it if it doesn't exist |

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

```powershell
New-ManagementScope `
  -Name "Expert Inbox Queue Mailboxes" `
  -RecipientRestrictionFilter "PrimarySmtpAddress -eq 'craigz@expertsvc.com' -or PrimarySmtpAddress -eq 'megan@expertsvc.com' -or PrimarySmtpAddress -eq 'joyce@expertsvc.com' -or PrimarySmtpAddress -eq 'casey@expertsvc.com' -or PrimarySmtpAddress -eq 'info@expertsvc.com' -or PrimarySmtpAddress -eq 'queue@expertsvc.com'"
```

Listing the addresses is verbose but obvious to read a year from now, which is
worth more than being clever. To change the list later:

```powershell
Set-ManagementScope -Identity "Expert Inbox Queue Mailboxes" -RecipientRestrictionFilter "<new filter>"
```

> A mail-enabled security group also works (`MemberOfGroup -eq '<distinguished
> name>'`), so adding a mailbox becomes a group membership change instead of a
> cmdlet. It needs the group's full DN from `Get-Group`. For six mailboxes that
> change once a year, the explicit list is easier to live with.

### 4c. Grant the two permissions, scoped

```powershell
New-ManagementRoleAssignment `
  -App "<Application ID>" `
  -Role "Application Mail.ReadWrite" `
  -CustomResourceScope "Expert Inbox Queue Mailboxes"

New-ManagementRoleAssignment `
  -App "<Application ID>" `
  -Role "Application Mail.Send" `
  -CustomResourceScope "Expert Inbox Queue Mailboxes"
```

What each one buys:

| Role | Needed for |
|---|---|
| `Application Mail.ReadWrite` | Reading mail, **and** writing the `Expert Queue` category onto it |
| `Application Mail.Send` | Sending replies as the mailbox they arrived at |

`Mail.ReadWrite` rather than `Mail.Read` is a deliberate trade for the Outlook
tagging — see [decisions.md](decisions.md). Drop the Outlook tagging and this
becomes `Application Mail.Read`, which is the safer grant.

> There's a bundled `Application Mail Full Access` role covering both. Two
> explicit assignments make the intent legible and let you revoke half.

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
| The six above | `True` |
| Anyone else | `False` |

**If an out-of-scope mailbox comes back `True`**, the app has an unscoped grant
somewhere. Almost always this means mail permissions were consented on the app
registration. Go back to Part 1, remove them from **API permissions**, and test
again.

`Test-ServicePrincipalAuthorization` deliberately bypasses the permission cache
so it tells you the truth immediately. Real API calls do not — see
[Troubleshooting](#troubleshooting).

---

## Part 6 — Create the Outlook category

The app writes a category named `Expert Queue` onto mail it has picked up. The
*colour* comes from each mailbox's own category list, so the category has to
exist there or the label shows up grey.

Creating it via the API would need a third permission (`MailboxSettings.ReadWrite`)
for something you do once. Do it by hand instead — about two minutes.

In Outlook, **for each of the six mailboxes**:

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
MONITORED_MAILBOXES=craigz@expertsvc.com,megan@expertsvc.com,joyce@expertsvc.com,casey@expertsvc.com,info@expertsvc.com
FORWARD_MAILBOX=queue@expertsvc.com
```

`queue@` is listed separately because mail arriving there is treated
differently — it's parsed as a forward to recover the original sender.

On Render these go in the environment group, never in a file.

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

You should see two rows, both with `Expert Inbox Queue Mailboxes` in
`CustomResourceScope`. A blank scope means the app has unscoped access — fix
that immediately, it's the thing this whole document exists to prevent.

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
