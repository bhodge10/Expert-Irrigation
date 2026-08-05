"""Sample messages, modelled line-for-line on real mail Craig supplied.

The structures here — field order, blank-line padding, quoting depth, the
boilerplate — reproduce the real thing exactly. **Customer names, addresses,
emails and phone numbers are invented.** The real messages stay out of the
repo; see docs/decisions.md.

Staff names are left as-is: they're the people who use the portal and already
appear in the seed data.

If you get a new sample that breaks a parser, add it here rather than fixing
the parser blind. That's what turns a bug report into a regression test.
"""

WEBSITE = "website@expertsvc.com"

# ---------------------------------------------------------------------------
# Contact form (expertsvc.com/contact/) — positional, no field labels.
# The blank-line padding mirrors what Outlook HTML flattens into.
# ---------------------------------------------------------------------------

CONTACT_FORM_LEAK = {
    "subject": "New Website Form Inquiry",
    "from_name": "Expert Irrigation",
    "from_email": WEBSITE,
    "to": ["craigz@expertsvc.com"],
    "body": """Dana Whitfield
dwhitfield@example.com
5135550142
Sprinkler Repair
118 Marston Ave
Cincinnati
45208
There is a large leak at what appears to be a pump point. I turned off the water going to the sprinkler system because it was just pumping out of the ground. There is a green plastic cover about 6" wide that is covering the hole where the leak is coming from.
Are you interested in a Virtual Estimate for Outdoor Lighting? Please submit image of the front of your house below?:

---

Date: July 23, 2026
Time: 1:47 am
Page URL: https://expertsvc.com/contact/
""",
}

# Two requests in one submission: a billing question and a scheduling question.
CONTACT_FORM_MIXED = {
    "subject": "New Website Form Inquiry",
    "from_name": "Expert Irrigation",
    "from_email": WEBSITE,
    "to": ["craigz@expertsvc.com"],
    "body": """Ed Marlow
emarlow@example.net
8595550163
Irrigation Services
904 Kilkenny Court
Fort Wright
41011
Could you send me a bill so I can pay it online? And what isthe date of my opening my sprinklers out thank you.
Are you interested in a Virtual Estimate for Outdoor Lighting? Please submit image of the front of your house below?:

---

Date: March 25, 2026
Time: 7:29 pm
Page URL: https://expertsvc.com/contact/
""",
}

# ---------------------------------------------------------------------------
# New-customer forms (expertsvc.com/new-customer/) — "Label: value".
# Both share a Page URL, so only the subject tells them apart.
# ---------------------------------------------------------------------------

INSTALL_FORM = {
    "subject": "New Customer Irrigation Installation Form",
    "from_name": "Expert Irrigation",
    "from_email": WEBSITE,
    "to": ["craigz@expertsvc.com"],
    "body": """First Name: Nathan
Last Name: Cole
Phone: 5135550188
Email: ncole@example.com
Address: 734 Stonehill Run
City and state of site to be serviced.:
KY:
OH: Other
IN:
Have you had a sprinkler system before?: No
What areas of the property are you interested in irrigating?: Entire yard
What is driving you to have a new sprinkler system installed?: Tired of dragging a hose
Is this new construction or existing?: Existing
When would you like the system installed?: Several Weeks/Months
Do you have a budget in mind?: No
Are you also interested in Outdoor Lighting?: Yes
Message:

---

Date: July 29, 2026
Time: 11:08 am
Page URL: https://expertsvc.com/new-customer/
""",
}

SERVICE_FORM = {
    "subject": "New Customer Irrigation Service Form",
    "from_name": "Expert Irrigation",
    "from_email": WEBSITE,
    "to": ["craigz@expertsvc.com"],
    "body": """First Name: Brian
Last Name: Teague
Phone: 8595550115
Email: bteague@example.com
Address: 1067 Aristides Drive
City and state of site to be serviced.:
KY: Union, KY
OH:
IN:
Are there any current issues with the sprinkler system that you are aware of?: No.
Are there any recent projects that may have affected the sprinkler system?: No.
How old is your Irrigation System?: Unsure
Was the system originally installed by a reputable irrigation contractor?: Yes
Does the system have a backflow preventer?: Yes
Has the system been serviced within the last 3 years?: Yes
Why are you searching for a new Irrigation contractor?: We are purchasing the home and the system was installed and serviced by Expert Irrigation. We are interested in learning about the service packages but also would like to have a fence installed in part of the backyard and we are curious/hopeful if the lines can be marked so they are not damaged.

---

Date: July 22, 2026
Time: 8:47 pm
Page URL: https://expertsvc.com/new-customer/
""",
}

# A contact form whose fields have been reordered — the failure mode the
# positional parser has to survive without mis-assigning anything.
CONTACT_FORM_MALFORMED = {
    "subject": "New Website Form Inquiry",
    "from_name": "Expert Irrigation",
    "from_email": WEBSITE,
    "to": ["craigz@expertsvc.com"],
    "body": """Sprinkler Repair
Gail Prentice
gprentice@example.com
5135550177
My back zone has stopped working entirely.

---

Date: July 23, 2026
Page URL: https://expertsvc.com/contact/
""",
}

# ---------------------------------------------------------------------------
# Direct customer mail
# ---------------------------------------------------------------------------

DIRECT_URGENT = {
    "subject": "Home system issue, immediately after mid summer check",
    "from_name": "Paul Hendry",
    "from_email": "phendry@example.com",
    "to": [
        "expertirrigation@zoomtown.com",
        "joyce@expertsvc.com",
        "kasiew@expertsvc.com",
        "craigz@expertsvc.com",
    ],
    "body": """We had our mid-summer check last monday and were told all was well and there were no issues.

Today we noticed that we have a significant leak at our backflow and have had to turn off water to the entire system.

We are leaving the country on Wednesday 7/15, and are counting on the system to keep things watered while we are away.

Can someone come look at and repair this in the next 2 days?

Thanks,

Paul Hendry
""",
}

# HOA manager forwards a resident's report to the builder; Craig is only CC'd.
FORWARDED_HOA = {
    "subject": "FW: ABERDEEN- Union KY.",
    "from_name": "Rachel Doyle",
    "from_email": "rachel.doyle@examplehoa.com",
    "to": ["kfields@examplehomes.com"],
    "cc": ["craigz@expertsvc.com"],
    "attachments": ["image001.jpg", "Video.mov"],
    "body": """Hi Karen,

It appears we have an active leak in Aberdeen. See below and attached. I am not sure if you/Expert are aware.

From: Alan Prescott <aprescott@example.com>

Sent: Wednesday, July 29, 2026 7:26 AM

To: Rachel Doyle <rachel.doyle@examplehoa.com>

Subject: ABERDEEN- Union KY.

Hi Rachel, I just wanted to make sure someone was aware. There is an active leak assuming it is a sprinkler head in Aberdeen and has been going on since yesterday. It is at

the front of the community.

Thank you
""",
}

# ---------------------------------------------------------------------------
# Threads: quoting, signatures, and the office talking to itself
# ---------------------------------------------------------------------------

# Craig replying to a customer, over a deep quote stack and two signatures.
THREADED_REPLY = {
    "subject": "Re: New Website Form Inquiry",
    "from_name": "Craig Zumdick",
    "from_email": "craigz@expertsvc.com",
    "to": ["gvance@example.com"],
    "body": """Gordon,

Thanks for the pictures.

Estimate for the new sensor and installed was forwarded to you for approval. Please approve online and we will order in preparation for your upcoming Start Up.

Thank you,

Craig Zumdick

Owner

Expert Irrigation & Outdoor Lighting

o: (859) 282-8101

www.expertsvc.com

From: Gordon Vance <gvance@example.com>

Sent: Wednesday, May 6, 2026 2:12 PM

To: Craig Zumdick <craigz@expertsvc.com>

Subject: Re: New Website Form Inquiry

Craig,

Not sure of any model #'s but here are some pics.

Thanks

Gordon
""",
}

# Joyce replying to Craig on the customer's own thread. This must become a note
# on the existing item, not a new queue item.
INTERNAL_REPLY = {
    "subject": "RE: New Website Form Inquiry",
    "from_name": "Joyce Saltzsieder",
    "from_email": "joyce@expertsvc.com",
    "to": ["craigz@expertsvc.com"],
    "body": """Mr. Ashbury will pay for his package online. I have Billy scheduled to meet with him the afternoon for 3/16 he has landscape lighting that some may need adjusting and some moved due to tree growth.

Thank-you for choosing Expert Irrigation & Outdoor Lighting!

Joyce Saltzsieder

Customer Service Representative / Install Co-Ordinator

Office (859)282-8101 ext.2

www.expertsvc.com

Please take a moment to leave us a Google review with the link below!

From: Craig Zumdick <craigz@expertsvc.com>

Sent: Thursday, February 19, 2026 10:02 AM

To: Joyce Saltzsieder <joyce@expertsvc.com>

Subject: Fwd: New Website Form Inquiry

Joyce,

Please follow up with Mr. Ashbury.
""",
}

# Automated mail that should never reach the queue.
NO_REPLY_VENDOR = {
    "subject": "Your order has shipped",
    "from_name": "Hunter Industries",
    "from_email": "no-reply@example-supplier.com",
    "to": ["craigz@expertsvc.com"],
    "body": "Your order #88213 has shipped and is expected Thursday.\n",
}

ALL = [
    CONTACT_FORM_LEAK,
    CONTACT_FORM_MIXED,
    CONTACT_FORM_MALFORMED,
    INSTALL_FORM,
    SERVICE_FORM,
    DIRECT_URGENT,
    FORWARDED_HOA,
    THREADED_REPLY,
    INTERNAL_REPLY,
    NO_REPLY_VENDOR,
]
