"""Microsoft Graph client.

Deliberately small: acquire a token, read new mail with delta queries, send a
reply as a mailbox, and tag a message. Nothing else.

Auth is client credentials. Note that the app registration carries **no** Graph
API permissions in Entra — access comes from an Exchange RBAC assignment scoped
to six mailboxes. If you're debugging a 403, read docs/azure-setup.md before
changing anything here; the answer is almost never in this file.
"""

import logging
import time
from typing import Any, Iterator

import httpx

from .config import settings

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

# Delta queries reject some $select combinations, so keep this list to fields
# that are actually needed downstream.
MESSAGE_FIELDS = ",".join(
    [
        "id",
        "conversationId",
        "subject",
        "from",
        "sender",
        "toRecipients",
        "ccRecipients",
        "receivedDateTime",
        "hasAttachments",
        "body",
        "bodyPreview",
        "isDraft",
    ]
)


class GraphError(RuntimeError):
    """A Graph call failed in a way worth surfacing to the operator."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GraphClient:
    def __init__(
        self,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.tenant_id = tenant_id or settings.ms_tenant_id
        self.client_id = client_id or settings.ms_client_id
        self.client_secret = client_secret or settings.ms_client_secret
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(timeout=timeout)

    # --- plumbing --------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _access_token(self) -> str:
        # Refresh a minute early so a token can't expire mid-request.
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        response = self._http.post(
            TOKEN_URL.format(tenant=self.tenant_id),
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
        if response.status_code != 200:
            raise GraphError(
                f"Could not get a token ({response.status_code}). "
                f"Check MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET. "
                f"{response.text[:300]}"
            )

        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """One Graph call, with token refresh and throttling handled."""
        for attempt in range(4):
            headers = kwargs.pop("headers", {}) or {}
            headers["Authorization"] = f"Bearer {self._access_token()}"
            response = self._http.request(method, url, headers=headers, **kwargs)

            if response.status_code == 401 and attempt == 0:
                # Token rejected — drop it and let the next pass fetch a new one.
                self._token = None
                continue

            if response.status_code == 429 or response.status_code >= 500:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                log.warning(
                    "Graph %s on %s; retrying in %.0fs", response.status_code, url, wait
                )
                time.sleep(min(wait, 60))
                continue

            return response

        raise GraphError(f"Graph kept failing on {method} {url}")

    # --- reading ---------------------------------------------------------

    def check_token(self) -> None:
        """Fetch a token now rather than on first use.

        Lets `manage.py checkgraph` separate "the credentials are wrong" from
        "the credentials work but a mailbox is out of scope".
        """
        self._access_token()

    def newest_message(self, mailbox: str) -> dict[str, Any] | None:
        """The newest inbox message, or None for an empty inbox.

        One cheap read that proves the token, the RBAC scope and the mailbox
        spelling together — the `manage.py checkgraph` probe. Never used for
        ingestion; the poller reads through delta_messages only.
        """
        response = self._request(
            "GET",
            f"{GRAPH}/users/{mailbox}/mailFolders/inbox/messages",
            params={"$top": 1, "$select": "subject,from,receivedDateTime"},
        )
        if response.status_code >= 400:
            raise GraphError(
                f"Reading {mailbox} failed ({response.status_code}): "
                f"{response.text[:300]}",
                status=response.status_code,
            )
        items = response.json().get("value", [])
        return items[0] if items else None

    def delta_messages(
        self, mailbox: str, delta_link: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """New and changed inbox messages since the last call.

        Returns the messages plus the delta link to store for next time. That
        stored link is what stops a restart re-ingesting the whole mailbox.
        """
        if delta_link:
            url = delta_link
            params = None
        else:
            url = f"{GRAPH}/users/{mailbox}/mailFolders/inbox/messages/delta"
            params = {"$select": MESSAGE_FIELDS}

        messages: list[dict[str, Any]] = []
        next_delta: str | None = None

        # Ask for a decent page size; Graph caps it anyway.
        headers = {"Prefer": "odata.maxpagesize=50"}

        while url:
            response = self._request("GET", url, params=params, headers=dict(headers))
            params = None  # only valid on the first call

            if response.status_code == 410:
                # Delta link expired. Start the mailbox again from scratch —
                # dedupe on graph_message_id stops that duplicating anything.
                log.warning("Delta link for %s expired; resyncing.", mailbox)
                return self.delta_messages(mailbox, None)

            if response.status_code >= 400:
                raise GraphError(
                    f"Reading {mailbox} failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )

            payload = response.json()
            messages.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
            next_delta = payload.get("@odata.deltaLink") or next_delta

        return messages, next_delta

    def delta_bootstrap(self, mailbox: str) -> str | None:
        """A delta link for "now", without walking the mailbox.

        $deltaToken=latest returns no messages, just the link. It's how the
        first sync of a big mailbox avoids paging years of history into
        memory — the backfill of recent mail happens separately, bounded,
        through messages_since.
        """
        response = self._request(
            "GET",
            f"{GRAPH}/users/{mailbox}/mailFolders/inbox/messages/delta",
            params={"$deltaToken": "latest"},
        )
        if response.status_code >= 400:
            raise GraphError(
                f"Bootstrapping {mailbox} failed ({response.status_code}): "
                f"{response.text[:300]}",
                status=response.status_code,
            )
        return response.json().get("@odata.deltaLink")

    def messages_since(self, mailbox: str, since_iso: str) -> list[dict[str, Any]]:
        """Inbox messages received on or after the given UTC ISO timestamp."""
        url = f"{GRAPH}/users/{mailbox}/mailFolders/inbox/messages"
        params: dict[str, Any] | None = {
            "$select": MESSAGE_FIELDS,
            "$filter": f"receivedDateTime ge {since_iso}",
            "$orderby": "receivedDateTime desc",
            "$top": 50,
        }

        messages: list[dict[str, Any]] = []
        while url:
            response = self._request("GET", url, params=params)
            params = None  # nextLink carries everything
            if response.status_code >= 400:
                raise GraphError(
                    f"Reading {mailbox} failed ({response.status_code}): "
                    f"{response.text[:300]}",
                    status=response.status_code,
                )
            payload = response.json()
            messages.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
        return messages

    def sent_messages(self, mailbox: str, top: int = 50) -> list[dict[str, Any]]:
        """Most recent sent mail — tone examples for drafting, never ingested."""
        response = self._request(
            "GET",
            f"{GRAPH}/users/{mailbox}/mailFolders/sentitems/messages",
            params={
                "$top": min(top, 100),
                "$select": "subject,body,bodyPreview,sentDateTime",
                "$orderby": "sentDateTime desc",
            },
        )
        if response.status_code >= 400:
            raise GraphError(
                f"Reading sent mail for {mailbox} failed ({response.status_code}): "
                f"{response.text[:300]}",
                status=response.status_code,
            )
        return response.json().get("value", [])

    def message_headers(self, mailbox: str, message_id: str) -> dict[str, str]:
        """Internet headers, used to spot bulk and list mail."""
        url = f"{GRAPH}/users/{mailbox}/messages/{message_id}"
        response = self._request(
            "GET", url, params={"$select": "internetMessageHeaders"}
        )
        if response.status_code >= 400:
            return {}
        entries = response.json().get("internetMessageHeaders") or []
        return {e.get("name", ""): e.get("value", "") for e in entries}

    # --- writing ---------------------------------------------------------

    def send_reply(self, mailbox: str, message_id: str, body_text: str) -> None:
        """Reply to a message as the mailbox it arrived at.

        The customer sees the mailbox, never the person who pressed Send —
        which is the point. Who actually sent it is recorded on our side.
        """
        url = f"{GRAPH}/users/{mailbox}/messages/{message_id}/reply"
        response = self._request("POST", url, json={"comment": body_text})
        if response.status_code >= 400:
            raise GraphError(
                f"Sending as {mailbox} failed ({response.status_code}): "
                f"{response.text[:300]}"
            )

    def set_categories(
        self, mailbox: str, message_id: str, categories: list[str]
    ) -> None:
        """Tag the source message in Outlook.

        Cosmetic. Callers must treat failure as non-fatal — a tag that didn't
        stick is a much smaller problem than a message that never got queued.
        """
        url = f"{GRAPH}/users/{mailbox}/messages/{message_id}"
        response = self._request("PATCH", url, json={"categories": categories})
        if response.status_code >= 400:
            raise GraphError(
                f"Tagging in {mailbox} failed ({response.status_code}): "
                f"{response.text[:200]}"
            )


def iter_mailboxes() -> Iterator[str]:
    yield from settings.mailbox_list
