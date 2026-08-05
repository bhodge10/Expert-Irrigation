# What the real mail actually looks like

Drawn from eight real messages Craig supplied (2026-02 to 2026-07). The
messages themselves stay out of the repo — see [decisions.md](decisions.md).
This file records the *shapes*, with no customer details in it.

Read this before writing the ingester or the classify prompt. Several things
here contradict reasonable-sounding assumptions.

---

## 1. Website forms arrive from an internal address

Every website form is sent by **`website@expertsvc.com`** to
`craigz@expertsvc.com`. The customer's name, email and phone are in the
**body**, not the headers.

Two consequences, both load-bearing:

**The "skip internal senders" rule must not skip `website@`.** The project
brief says to skip `@expertsvc.com` senders as internal chatter. Applied
literally, that discards every website form — which is a large share of real
intake, and the highest-intent share. `website@expertsvc.com` is an inbound
customer channel wearing an internal return address.

**`from_email` has to be re-derived from the body** for form submissions, or
every form in the queue shows as being from `website@expertsvc.com`, replies go
to the wrong place, and per-sender rules can never work.

---

## 2. There are three different forms, and they are not the same shape

The `Page URL` line at the bottom of each is what tells them apart.

### Contact form — `expertsvc.com/contact/`

**Positional, no field labels.** Values appear one per line in a fixed order:

```
<name>
<email>
<phone>
<service type>          e.g. "Irrigation Services", "Sprinkler Repair"
<street address>
<city>
<zip>
<free-text message>     one or more lines
Are you interested in a Virtual Estimate for Outdoor Lighting? …   ← boilerplate, always present
---
Date: <date>
Time: <time>
Page URL: https://expertsvc.com/contact/
```

Parsing this is position-dependent and therefore brittle: if the form is ever
reordered or a field is added, the parser silently mis-assigns every field.
Guard it — validate that line 2 looks like an email and line 3 like a phone
number, and if not, fall back to treating the whole thing as free text rather
than filing garbage.

The trailing "Virtual Estimate" line is boilerplate on every submission and
must be stripped before classification, or the model sees an outdoor-lighting
sales pitch on every single form and drifts toward Sales.

### New Customer Irrigation **Installation** form — `expertsvc.com/new-customer/`

`Label: value` pairs — much easier. Fields seen:

```
First Name / Last Name / Phone / Email / Address
City and state of site to be serviced.:   ← header line, then KY: / OH: / IN: sub-lines
Have you had a sprinkler system before?
What areas of the property are you interested in irrigating?
What is driving you to have a new sprinkler system installed?
Is this new construction or existing?
When would you like the system installed?
Do you have a budget in mind?
Are you also interested in Outdoor Lighting?
Message:
```

**This form is Sales by definition.** Someone filling it in wants a system
installed. Classification barely needs the model.

### New Customer Irrigation **Service** form — `expertsvc.com/new-customer/`

Also `Label: value`. Different questions:

```
First Name / Last Name / Phone / Email / Address
City and state of site to be serviced.:   ← same KY/OH/IN sub-line pattern
Are there any current issues with the sprinkler system that you are aware of?
Are there any recent projects that may have affected the sprinkler system?
How old is your Irrigation System?
Was the system originally installed by a reputable irrigation contractor?
Does the system have a backflow preventer?
Has the system been serviced within the last 3 years?
Why are you searching for a new Irrigation contractor?
```

Note both `new-customer` forms share a Page URL, so **the URL alone doesn't
identify the form** — key off the subject line or the field names.

> **Worth doing before Phase 3:** these forms are structured data being
> flattened into prose so a model can read it back out. If the form platform
> can post to a webhook, or put a hidden `form_type` field in the email, most
> of this parsing evaporates. Ask what the website runs on.

---

## 3. One email routinely contains two requests

This is the finding that doesn't fit the current data model.

Real examples, paraphrased:

- *"Can you confirm I'm signed up for 2026 services and whether I've paid?
  **Also** I'd like an estimate to upgrade the lighting in the back yard."*
  → an account/billing question **and** a lighting sales lead.
- *"Could you send me a bill so I can pay online? **And** what's the date for
  my sprinkler opening?"* → billing **and** scheduling.
- *"We're buying the home and want to hear about service packages — **and**
  we're installing a fence, can the lines be marked so they aren't damaged?"*
  → membership sales **and** a line-locate service call.

Craig's own reply to the first one splits it across two people: Joyce handles
the account question, Jordan is sent out for the lighting estimate.

The queue currently models one message → one queue → one assignee. On mail like
this it forces a false choice, and whichever half loses gets dropped — which is
exactly the failure the portal exists to prevent.

**Unresolved.** Options, cheapest first:

1. **Primary queue + secondary flag.** One queue as today, plus "also needs
   Sales". Small change, keeps the UI simple, doesn't really model two owners.
2. **Split into linked items.** Ingest creates two queue rows sharing a
   `conversation_id`, each independently assignable and closable. Honest, and
   the closest match to what Craig actually does. Costs a "split this" UI and
   a way to avoid double-replying to the customer.
3. **Multiple assignees on one message.** Models the people but not the work —
   "handled" becomes ambiguous when one person is done and the other isn't.

Leaning toward (2), but it's Craig's call — the question to put to him is
*"when one email asks for two things, do you want one item or two?"*

---

## 4. Craig is often not the recipient

One sample: a resident reports a leak to their **HOA property manager**, who
forwards it to the **builder**, who has Craig on **CC**.

So: the sender is not the customer, the account is a community rather than a
person, and Craig is a CC rather than a To. It still arrives in his mailbox and
still needs dispatching.

Implications:

- Don't assume `To:` contains a monitored mailbox — **check `Cc:` too**.
- `from_email` is the property manager, not the person with the problem. Any
  ServiceTitan matching in Phase 4 has to cope with that.
- Commercial/HOA accounts behave differently from homeowners and may warrant
  their own handling later.

---

## 5. The same email lands in several monitored mailboxes

One sample was addressed to four Expert addresses at once. Dedupe on
`graph_message_id` is not an edge case — it's the normal path, and it will be
exercised on day one.

A **legacy address, `expertirrigation@zoomtown.com`**, also appears as a live
recipient alongside the `@expertsvc.com` ones. Find out whether it still
receives customer mail; if it does it needs monitoring, and if it doesn't it
should be retired.

---

## 6. Bodies are HTML, and mostly not the message

Every sample had an **empty plain-text body** — the content is HTML only. The
ingester must read the HTML body and flatten it; reading `body` alone yields
nothing.

Once flattened, most of the text still isn't the message:

- **Quoted history.** Threads run to four levels of `From:/Sent:/To:/Subject:`
  quoting. The newest reply is often two lines above a page of history.
- **Signature blocks.** Staff signatures carry titles, phone extensions,
  a website, and a Google-review link.
- **Boilerplate.** The forms' "Virtual Estimate" line, every time.

All three must be stripped before classification, or the model classifies a
signature. Strip for the model; **keep the full text for display** — the office
sometimes needs the history.

---

## 7. Customers send photos and video

One sample carried a 6.9 MB video, another three phone photos. A thread in the
samples is literally Craig asking for pictures and the customer replying with
them.

The data model has no attachment support at all. At minimum the queue should
show that attachments exist and how many — a leak report with a photo is worth
opening before one without.

---

## 8. Urgency, in customers' own words

Real signals from the samples:

- *"significant leak at our backflow, have had to turn off water to the entire
  system"* — plus *"leaving the country Wednesday"* and *"in the next 2 days"*
- *"active leak … has been going on since yesterday"*
- *"large leak … just pumping out of the ground"*

Two patterns to encode: **water loss the customer has already tried to stop**
(they shut the system off — it's still bad), and **a hard deadline**
(travelling, closing, event). Both belong in the urgency rule.

---

## 9. Internal conversation happens on the customer thread

Staff reply to each other on the same thread the customer email arrived on
(*"Mr. X will pay online. I have Billy scheduled to meet him 3/16"* →
*"Got it, thanks"*).

If those get ingested as new customer mail, the queue fills with the office
talking to itself. If they're skipped outright, the office loses context that
belongs on the message.

They should become **internal notes on the existing item**, not new queue
items. There's no internal-notes feature yet; this is a real gap.

---

## What this changes

| Finding | Effect |
|---|---|
| Forms come from `website@` | Skip rule must whitelist it, or all forms are lost |
| Customer identity is in the form body | `from_email` re-derived, or replies go nowhere |
| Two requests in one email | Data model question — needs Craig's answer |
| Craig on CC | Match monitored mailboxes against To **and** Cc |
| Bodies are HTML-only | Flatten HTML; plain-text body is empty |
| Quotes and signatures dominate | Strip before classify, keep for display |
| Attachments are common | Not modelled at all |
| Internal replies on thread | Should be notes, not queue items |
