"""Reading customer email.

Everything in this package is pure: text in, text out, no network and no
database. That's deliberate — it means the awkward parts (three website form
layouts, forwarded headers, four levels of quoting) can be tested against real
samples without a Microsoft tenant.

The Graph plumbing lives in app/graph.py; the decision about what to do with a
parsed message lives in app/mail/rules.py.
"""
