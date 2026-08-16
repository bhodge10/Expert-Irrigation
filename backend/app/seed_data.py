"""Fixture data for local development.

The five office users, plus ten messages borrowed from the design mockup.
Timestamps are expressed as "minutes ago" so a fresh seed always looks like a
normal morning rather than a museum piece.

Nothing here runs in production. See backend/manage.py.
"""

# key -> (email, display_name, initials, color, role)
USERS = {
    "craig": ("craigz@expertsvc.com", "Craig Zumdick", "CZ", "#1F7A47", "Owner"),
    "megan": ("megan@expertsvc.com", "Megan", "M", "#1D6E9C", "Office"),
    "joyce": ("joyce@expertsvc.com", "Joyce", "J", "#7A4FA3", "Service scheduling"),
    "casey": ("casey@expertsvc.com", "Casey", "C", "#B96C0C", "Office"),
    "jordan": ("jordan@expertsvc.com", "Jordan", "JD", "#A9342A", "Sales / estimating"),
}

MESSAGES = [
    {
        "minutes_ago": 49,
        "mailbox": "craigz@expertsvc.com",
        "from_name": "Ron Delaney",
        "from_email": "rdelaney74@gmail.com",
        "subject": "Water running down the driveway — need someone today",
        "body_text": (
            "Craig,\n\n"
            "Woke up to water pouring out of the mulch bed by the mailbox and running "
            "all the way down the driveway into the street. I shut the system off at "
            "the controller but it's still seeping. Looks like the line itself, not a "
            "head.\n\n"
            "I'm home all day. Please call my cell, 859-555-0147.\n\n"
            "Ron"
        ),
        "queue": "service",
        "confidence": 96,
        "is_urgent": True,
        "classification_reasons": [
            "Active water loss described — flagged high priority",
            "Customer already shut off the controller",
            "Existing member: Gold plan, Hebron",
        ],
        "assignee": None,
    },
    {
        "minutes_ago": 81,
        "mailbox": "info@expertsvc.com",
        "from_name": "Katie Brennan",
        "from_email": "kbrennan@outlook.com",
        "subject": "Sprinkler head soaking the driveway",
        "body_text": (
            "Hi there — one of the heads on the front right side is spraying across "
            "the driveway instead of the lawn. It's been doing it since the spring "
            "startup. Nothing else seems wrong with the system.\n\n"
            "No rush, but we'd like it looked at before the next round of hot "
            "weather. Afternoons are best for us.\n\n"
            "Thanks,\nKatie Brennan\n859-555-0182"
        ),
        "queue": "service",
        "confidence": 94,
        "is_urgent": False,
        "classification_reasons": [
            "Repair on an existing system — service queue",
            "Nozzle spray-arc adjustment, one head",
            "Afternoon preference noted for dispatch",
        ],
        "assignee": "joyce",
    },
    {
        "minutes_ago": 123,
        "mailbox": "craigz@expertsvc.com",
        "from_name": "Tom & Lisa Whitaker",
        "from_email": "lwhitaker@icloud.com",
        "subject": "Landscape lighting quote — new build, ready this fall",
        "body_text": (
            "Craig,\n\n"
            "We're finishing a new build in Indian Hill and the landscaping goes in "
            "at the end of August. We'd like to talk about lighting — uplighting on "
            "the front elevation, path lights along the walk, and something for the "
            "back patio and steps.\n\n"
            "Also curious whether you handle irrigation at the same time, since the "
            "yard is bare right now.\n\n"
            "What's the best way to get on your calendar for an estimate?\n\n"
            "Tom Whitaker\n513-555-0119"
        ),
        "queue": "sales",
        "confidence": 91,
        "is_urgent": False,
        "classification_reasons": [
            "New install, no existing account — sales queue",
            "Both lighting and irrigation mentioned",
            "Timing tied to landscape install, end of August",
        ],
        "assignee": None,
    },
    {
        "minutes_ago": 167,
        "mailbox": "joyce@expertsvc.com",
        "from_name": "Marcus Hall",
        "from_email": "mhall.contracting@gmail.com",
        "subject": "Need to move Thursday's appointment",
        "body_text": (
            "Good morning — we have someone scheduled to come out Thursday morning "
            "for the backflow test. I have to be out of town that day. Can we push it "
            "to the following week? Any morning works except Wednesday.\n\n"
            "Thanks,\nMarcus"
        ),
        "queue": "undetermined",
        "confidence": 88,
        "is_urgent": False,
        "classification_reasons": [
            "Reschedule on an existing job — not a new request",
            "Availability given: any morning except Wednesday",
            "Matches an open Thursday backflow appointment",
        ],
        "assignee": None,
    },
    {
        "minutes_ago": 190,
        "mailbox": "megan@expertsvc.com",
        "from_name": "Sandra Cole",
        "from_email": "sandracole@gmail.com",
        "subject": "Deck lights buzzing, half the run is out",
        "body_text": (
            "The transformer by the garage has started making a humming noise, and "
            "about half the lights along the deck stairs stopped coming on last week. "
            "The rest still work.\n\n"
            "We've had the system about four years. Is this something you can look "
            "at, or is it time to replace the whole thing?\n\n"
            "Sandra"
        ),
        "queue": "service",
        "confidence": 73,
        "is_urgent": False,
        "classification_reasons": [
            "Repair language, but the replacement question could push it to sales",
            "Lighting transformer plus a partial run out",
            "Low confidence — worth confirming the queue",
        ],
        "assignee": None,
    },
    {
        "minutes_ago": 233,
        "mailbox": "info@expertsvc.com",
        "from_name": "Website form — New Customer",
        "from_email": "forms@expertsvc.com",
        "subject": "New customer form: Jen Ostrowski — Gold membership + spring startup",
        "body_text": (
            "Name: Jen Ostrowski\n"
            "Address: Burlington, KY 41005\n"
            "Phone: 859-555-0166\n"
            "Service needed: Membership plan\n"
            "System age: 6 zones, installed by previous owner\n\n"
            "Message: We just bought the house and there's a sprinkler system we've "
            "never run. Interested in the Gold membership and getting it started up "
            "and inspected. Who installed it originally, we have no idea."
        ),
        "queue": "sales",
        "confidence": 97,
        "is_urgent": False,
        "classification_reasons": [
            "Submitted through the New Customer form",
            "Membership plan interest — sales queue",
            "No account on file; new contact",
        ],
        "assignee": "jordan",
    },
    {
        "minutes_ago": 268,
        "mailbox": "craigz@expertsvc.com",
        "from_name": "Priya Raghavan",
        "from_email": "praghavan@ncwd.example.org",
        "subject": "Backflow certificate copy for the water district",
        "body_text": (
            "Hello — the water district is asking for a copy of the backflow test "
            "certificate for our address from this spring. I can't find our copy. "
            "Could you send it over?\n\n"
            "Thank you,\nPriya Raghavan"
        ),
        "queue": "undetermined",
        "confidence": 92,
        "is_urgent": False,
        "classification_reasons": [
            "Records request — no work to schedule",
            "April backflow certificate is on file",
            "No dispatch needed",
        ],
        "assignee": "megan",
    },
    {
        "minutes_ago": 1580,
        "mailbox": "craigz@expertsvc.com",
        "from_name": "Dave Kuntz — Kuntz Homes",
        "from_email": "dkuntz@kuntzhomes.example.com",
        "subject": "Irrigation bid — 12 lots, Ridgewater phase 2",
        "body_text": (
            "Craig,\n\n"
            "We're breaking ground on phase 2 in September, twelve lots. Looking for "
            "a per-lot irrigation number and what your lead time looks like if we "
            "stagger them through the fall.\n\n"
            "I can send the plat and lot dimensions if you tell me what you need. "
            "We'd want the same spec across all twelve.\n\n"
            "Dave"
        ),
        "queue": "sales",
        "confidence": 84,
        "is_urgent": False,
        "classification_reasons": [
            "Commercial / builder bid — larger than a single-home quote",
            "Twelve lots, staggered fall schedule",
            "Requesting plans; estimator should respond directly",
        ],
        "assignee": None,
    },
    {
        "minutes_ago": 1655,
        "mailbox": "megan@expertsvc.com",
        "from_name": "Bill Hoffman",
        "from_email": "whoffman@gmail.com",
        "subject": "Question on invoice 14822",
        "body_text": (
            "I was billed a service call fee on the last visit, but I'm on the Silver "
            "plan and thought that was reduced. Can someone take a look at invoice "
            "14822?\n\n"
            "Bill Hoffman"
        ),
        "queue": "undetermined",
        "confidence": 79,
        "is_urgent": False,
        "classification_reasons": [
            "Billing question — no service to dispatch",
            "Member discount may not have been applied",
            "References invoice 14822",
        ],
        "assignee": None,
    },
    {
        "minutes_ago": 1730,
        "mailbox": "info@expertsvc.com",
        "from_name": "Doug Mercer",
        "from_email": "dmercer1962@yahoo.com",
        "subject": "Zone 4 won't come on",
        "body_text": (
            "Zones 1 through 3 run fine but zone 4 does nothing, no water at all. "
            "Tried running it manually from the controller and still nothing. "
            "Everything worked last season.\n\n"
            "Doug Mercer\n859-555-0133"
        ),
        "queue": "service",
        "confidence": 90,
        "is_urgent": False,
        "classification_reasons": [
            "Single zone dead, others functioning — likely valve or solenoid",
            "Manual run already attempted",
            "Existing account, system serviced last spring",
        ],
        "assignee": "joyce",
    },
]
