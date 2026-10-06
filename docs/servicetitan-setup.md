# Connecting to ServiceTitan (Phase 4, read-only)

What was done on 2026-10-05 to give the portal a read-only view of
ServiceTitan, written so it can be redone from nothing. The *why* — what the
plan allows, what the API terms forbid, and the design choices that fell out
of them — is the ServiceTitan entry in [decisions.md](decisions.md). Read that
first if you're about to change anything here.

The outcome: one app, **Expert Inbox Queue**, registered under Expert
Irrigation's own ServiceTitan account, holding **View** on eight resources and
nothing else. Four values on Render let the portal use it.

---

## Part 1 — Is the package right?

Customer-built apps exist only on **The Works** and **Enterprise Plus**.
Expert Irrigation's package passed this test on 2026-10-05: the tenant
credentials portal opened and let an app be registered. If a future sign-in
lands on a "request access" page instead, the package changed — talk to
ServiceTitan before anything else.

## Part 2 — Register the app

Sign in at <https://developer.servicetitan.io>. Use the **ServiceTitan
Customers** side, **Sign In as Production Environment User**, with a normal
ServiceTitan login for Expert Irrigation's tenant. (The Third-Party Developers
side is for partner organisations with their own integration environment —
not this.) The login needs two ServiceTitan permissions, which an admin grants
on the user: **Generate API Application Key** and **Manage API Application
Access**.

The app was registered under Brad's own named login, issued by Expert
Irrigation. That's the arrangement the API terms allow for an IT provider
(§2.2) — a login of his own, under the customer's account. Never register the
app under someone else's login, and never let an outside party hold the App
Key: ServiceTitan calls that "tunneling" and prohibits it.

**My Apps → Register New App.** What was entered, and why:

| Field | Value | Why |
|---|---|---|
| Organization Name | Expert Irrigation | The app belongs to the customer, not Simple IT |
| Organization/App Website | Expert Irrigation's public site | Stable; the Render URL would also be accepted |
| Email Address | Brad's | Where ServiceTitan sends API deprecation and change notices |
| App Name | Expert Inbox Queue | Matches the Render service name |
| App Category | Communications → Other | Not "Conversational AI" — that means an AI that talks to customers directly; ours drafts text a person reviews and sends |
| Description | See below | Carries the AI disclosure the terms require at registration |
| Credentials configured by | "I, the app developer, will configure the credentials on behalf of each tenant" | They live in Render's environment; there's no screen for anyone to type them into |

The description as submitted (keep any rewrite saying the same three things:
read-only, display-only, AI disclosed):

> Internal inbox-triage portal for Expert Irrigation staff. The portal sorts
> incoming customer email (service requests, sales inquiries) into work queues
> and lets staff reply from within it. This integration adds a read-only
> ServiceTitan lookup: when a message is opened, the portal matches the sender
> by phone number or name against ServiceTitan customers and displays their
> account, active membership, and open jobs alongside the email. Read-only
> access to CRM, Memberships, and Jobs. No data is written to ServiceTitan.
> The portal uses an AI model (Anthropic Claude) for email classification and
> reply drafting; ServiceTitan data is shown to Expert Irrigation staff only
> and is never sent to the AI model or stored beyond 24 hours. Built and
> maintained for Expert Irrigation by its IT services provider, Simple IT.

**Scopes.** Read (View) on exactly these eight, and no Modify anywhere:

```
Contacts, Customers, Locations            (CRM)
Appointments, Jobs, Job Types             (JPM)
Customer Memberships, Membership Types    (Memberships)
```

Job Types and Membership Types are reference data — without them the card
would show "membership type 3" instead of the plan's name. Writes (creating
customers or leads, rescheduling) are a separate, later decision; adding any
scope creates a new scopes version that the tenant has to approve again
(Part 3).

After **Register App**, the App Key is under **Keys → Application Key**. It's
the same key in production and the integration environment.

## Part 3 — Let the tenant approve it, then get the client credentials

The app isn't usable until the tenant allows it. In ServiceTitan itself (not
the developer portal): **Settings → Integrations → API Application Access**,
find Expert Inbox Queue, **Connect**, and approve the listed scopes. Same two
permissions needed as in Part 2.

Back in the developer portal, **My Apps → the app → App Connections** now
shows the tenant row with **Allowed by Tenant** green, the **Tenant/Network
ID**, and the **Client ID**. Generate the **Client Secret** on that row — it's
shown once. Generate a second one later if a separate secret for local
development is wanted; they're independently revocable.

Whenever the scopes change, the tenant re-approves in the same Settings page
and the row shows the new scopes version.

## Part 4 — Where the values go

Four values, named as in `.env.example`:

| Variable | From |
|---|---|
| `SERVICETITAN_APP_KEY` | Part 2, Keys → Application Key |
| `SERVICETITAN_TENANT_ID` | Part 3, the Tenant/Network ID on the connection row |
| `SERVICETITAN_CLIENT_ID` | Part 3, the connection row |
| `SERVICETITAN_CLIENT_SECRET` | Part 3, generated on the connection row |

Locally they go in the repo-root `.env`. On Render they go in the
`expert-inbox-secrets` environment group, which both the web service and the
poller read (render-deploy.md). `SERVICETITAN_ENVIRONMENT` stays unset or
`production`; see Part 5 for the other value.

Then prove it from the app's side:

```powershell
cd backend
.venv\Scripts\python.exe manage.py checkservicetitan
```

It fetches a token, then reads **one record from each of the eight scopes**
and prints the record count — never a record. Every line should say `ok`.
`DENIED` on a scope means it isn't on the app, or the tenant hasn't
re-approved since the scopes changed. `No token` means the client ID or
secret is wrong, or was issued for the other environment.

## Part 5 — The integration environment (optional, not yet requested)

ServiceTitan will provision an **Integration Environment**: a clone of
production, with production data, for development and testing. Request it by
emailing **integrations@servicetitan.com** from Expert Irrigation's side. It
has its own logins and its own client ID and secret (the App Key carries
over). To point the app at it, set `SERVICETITAN_ENVIRONMENT=integration`
and use the credentials issued there.

As of 2026-10-05 it hasn't been requested. The read-only connection was proven
straight against production, which the eight View scopes make safe.

## What the app must never do

These come from the API Terms of Use and are design constraints, not
preferences (decisions.md has the clause numbers):

- **ServiceTitan data is display-only.** It appears in the detail pane and is
  never put into a classify or draft prompt, never into the few-shot
  examples, never into the training signal.
- **Nothing is cached beyond 24 hours.** No local mirror of the customer list.
- **No AI chooses endpoints.** Every lookup is deterministic code.
- **The AI disclosure in the description stays accurate.** If the portal's
  AI use changes in a way that touches ServiceTitan data, update the
  description and tell ServiceTitan before shipping it.

---

## Troubleshooting

**`No token` with a 400.** Client ID or secret mistyped, or they were issued
for the other environment. Regenerate the secret on the connection row and
try again.

**`DENIED` on one scope, the rest `ok`.** The scope was added to the app but
the tenant hasn't approved the new scopes version. Part 3.

**`DENIED` on everything, token fine.** Allowed by Tenant isn't green — the
connection was never approved, or was revoked in Settings → Integrations →
API Application Access.

**The lookup card is blank but the check passes.** The card only runs when
all four variables are set on the service that serves the portal. Check the
environment group is attached to the web service, not just the poller.
