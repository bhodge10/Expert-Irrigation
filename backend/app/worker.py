"""The background poller.

Runs as its own Render service:  python -m app.worker

Reads each monitored mailbox on a loop and files whatever is new. Deliberately
boring — no scheduler library, no queue, just a loop with a sleep. At six
mailboxes on a 60-second cycle there is nothing here worth the complexity of
anything cleverer.
"""

import logging
import signal
import sys
import time

from .config import settings
from .db import SessionLocal
from .graph import GraphClient
from .ingest import poll_all

log = logging.getLogger("worker")

_stop = False


def _handle_stop(signum, _frame) -> None:
    """Finish the mailbox we're on, then exit cleanly."""
    global _stop
    log.info("Signal %s received — stopping after this cycle.", signum)
    _stop = True


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    )

    if not settings.graph_configured:
        log.error(
            "Microsoft Graph isn't configured. Set MS_TENANT_ID, MS_CLIENT_ID "
            "and MS_CLIENT_SECRET. See docs/azure-setup.md."
        )
        return 1

    mailboxes = settings.mailbox_list
    if not mailboxes:
        log.error("No mailboxes to poll. Set MONITORED_MAILBOXES.")
        return 1

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    log.info(
        "Polling %d mailbox(es) every %ds: %s",
        len(mailboxes),
        settings.poll_seconds,
        ", ".join(mailboxes),
    )
    if not settings.outlook_category:
        log.info("Outlook tagging is off (OUTLOOK_CATEGORY is empty).")

    with GraphClient() as graph:
        while not _stop:
            started = time.monotonic()
            db = SessionLocal()
            try:
                result = poll_all(db, graph)
                if result.created or result.noted or result.failed:
                    log.info("Cycle complete: %s", result)
            except Exception:
                # A cycle failing must never kill the worker — Render would
                # restart it, and a crash loop is harder to diagnose than a
                # logged error.
                log.exception("Poll cycle failed; continuing.")
            finally:
                db.close()

            elapsed = time.monotonic() - started
            remaining = settings.poll_seconds - elapsed
            while remaining > 0 and not _stop:
                time.sleep(min(1.0, remaining))
                remaining -= 1.0

    log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
