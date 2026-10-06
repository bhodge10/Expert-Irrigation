"""ServiceTitan client — Phase 4.

Read-only, and deliberately so. The app registration carries View scopes on
eight resources and nothing else (docs/servicetitan-setup.md). What comes
back is shown to staff in the detail pane and goes nowhere else — never into
a prompt, never into the training signal, never kept past a day. The
reasoning is the ServiceTitan entry in docs/decisions.md.

Three things identify a call: the **App Key** (which app this is, sent as the
``ST-App-Key`` header on every request), the **Client ID + Secret** (which
tenant connection, exchanged for a 15-minute bearer token) and the **tenant
ID** in every URL. The tenant ID is not a secret; the other three are.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

# (API base, token endpoint). Credentials are issued per environment; the
# app key is the same in both.
ENVIRONMENTS = {
    "production": (
        "https://api.servicetitan.io",
        "https://auth.servicetitan.io/connect/token",
    ),
    "integration": (
        "https://api-integration.servicetitan.io",
        "https://auth-integration.servicetitan.io/connect/token",
    ),
}

# Every read scope the app holds, named as the developer portal names them,
# with the list endpoint that proves it. `manage.py checkservicetitan` reads
# one record from each; the lookup methods below use the same paths.
SCOPES: list[tuple[str, str]] = [
    ("Customers", "crm/v2/tenant/{t}/customers"),
    ("Contacts", "crm/v2/tenant/{t}/contacts"),
    ("Locations", "crm/v2/tenant/{t}/locations"),
    ("Jobs", "jpm/v2/tenant/{t}/jobs"),
    ("Appointments", "jpm/v2/tenant/{t}/appointments"),
    ("Job Types", "jpm/v2/tenant/{t}/job-types"),
    ("Customer Memberships", "memberships/v2/tenant/{t}/memberships"),
    ("Membership Types", "memberships/v2/tenant/{t}/membership-types"),
]

# Job statuses that mean "somebody still has to go out there".
OPEN_JOB_STATUSES = ("Scheduled", "Dispatched", "InProgress", "Hold")


class ServiceTitanError(RuntimeError):
    """A ServiceTitan call failed in a way worth surfacing to the operator."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProbeResult:
    scope: str
    ok: bool
    total: int | None = None
    detail: str = ""


# --- phone numbers ---------------------------------------------------------

# A North American number written any of the usual ways. The digit guards at
# both ends stop a 10-digit slice being lifted out of an order number or a
# tracking code.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]*)?\(?(\d{3})\)?[\s.-]*(\d{3})[\s.-]*(\d{4})(?!\d)"
)


def normalize_phone(raw: str | None) -> str | None:
    """Ten digits, or None if that isn't what we were given."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def find_phones(text: str | None) -> list[str]:
    """Every distinct phone number in a block of text, normalised, in order."""
    found: list[str] = []
    for match in _PHONE_RE.finditer(text or ""):
        number = "".join(match.groups())
        if number not in found:
            found.append(number)
    return found


# --- the client ------------------------------------------------------------


class ServiceTitanClient:
    def __init__(
        self,
        *,
        app_key: str | None = None,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        environment: str | None = None,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.app_key = app_key or settings.servicetitan_app_key
        self.tenant_id = tenant_id or settings.servicetitan_tenant_id
        self.client_id = client_id or settings.servicetitan_client_id
        self.client_secret = client_secret or settings.servicetitan_client_secret

        env = environment or settings.servicetitan_environment or "production"
        env = env.strip().lower()
        if env not in ENVIRONMENTS:
            raise ValueError(
                f"SERVICETITAN_ENVIRONMENT must be one of "
                f"{', '.join(ENVIRONMENTS)}, not {env!r}."
            )
        self.environment = env
        self.api_base, self.token_url = ENVIRONMENTS[env]

        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(timeout=timeout, transport=transport)

    # --- plumbing --------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ServiceTitanClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _access_token(self) -> str:
        # Tokens last 15 minutes. Refresh a minute early so one can't expire
        # between the check here and the request that uses it.
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        response = self._http.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if response.status_code != 200:
            raise ServiceTitanError(
                f"Could not get a token ({response.status_code}). Check "
                f"SERVICETITAN_CLIENT_ID / SERVICETITAN_CLIENT_SECRET, and "
                f"that SERVICETITAN_ENVIRONMENT matches where they were "
                f"issued. {response.text[:300]}",
                status=response.status_code,
            )

        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 900))
        return self._token

    def _url(self, path: str) -> str:
        return f"{self.api_base}/{path.format(t=self.tenant_id)}"

    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """One ServiceTitan call, with token refresh and throttling handled."""
        url = self._url(path)
        for attempt in range(4):
            headers = {
                "Authorization": f"Bearer {self._access_token()}",
                "ST-App-Key": self.app_key,
            }
            response = self._http.request(method, url, headers=headers, params=params)

            if response.status_code == 401 and attempt == 0:
                # Token rejected — drop it and let the next pass fetch a new one.
                self._token = None
                continue

            if response.status_code == 429 or response.status_code >= 500:
                wait = float(response.headers.get("Retry-After", 2**attempt))
                log.warning(
                    "ServiceTitan %s on %s; retrying in %.0fs",
                    response.status_code,
                    url,
                    wait,
                )
                time.sleep(min(wait, 60))
                continue

            return response

        raise ServiceTitanError(f"ServiceTitan kept failing on {method} {url}")

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        """A GET that is expected to succeed. Anything else is an error."""
        clean = {k: v for k, v in params.items() if v is not None}
        response = self._request("GET", path, params=clean)
        if response.status_code >= 400:
            raise ServiceTitanError(
                f"GET {path.format(t=self.tenant_id)} failed "
                f"({response.status_code}): {response.text[:300]}",
                status=response.status_code,
            )
        return response.json()

    def _list(self, path: str, **params: Any) -> list[dict[str, Any]]:
        return self._get(path, **params).get("data") or []

    # --- proving the connection ------------------------------------------

    def check_token(self) -> None:
        """Fetch a token now rather than on first use — separates "the
        credentials are wrong" from "a scope is missing"."""
        self._access_token()

    def probe(self) -> list[ProbeResult]:
        """One record from each scoped endpoint. The checkservicetitan probe.

        Read-only by construction; asks for the record count so the output
        says something about the tenant without printing anyone's details.
        """
        results: list[ProbeResult] = []
        for scope, path in SCOPES:
            response = self._request(
                "GET", path, params={"pageSize": 1, "includeTotal": "true"}
            )
            status = response.status_code
            if status in (401, 403):
                results.append(
                    ProbeResult(
                        scope,
                        False,
                        detail="DENIED — the scope isn't on the app, or the "
                        "tenant hasn't re-approved it since the scopes changed. "
                        "See docs/servicetitan-setup.md, Part 3.",
                    )
                )
            elif status == 404:
                results.append(
                    ProbeResult(
                        scope,
                        False,
                        detail=f"NOT FOUND — {path.format(t=self.tenant_id)} "
                        "no longer exists; the API may have moved.",
                    )
                )
            elif status >= 400:
                results.append(
                    ProbeResult(
                        scope, False, detail=f"FAILED — {status}: {response.text[:120]}"
                    )
                )
            else:
                total = response.json().get("totalCount")
                results.append(
                    ProbeResult(scope, True, total=int(total) if total is not None else None)
                )
        return results

    # --- lookups (all reads) ---------------------------------------------

    def find_customers_by_phone(self, phone: str) -> list[dict[str, Any]]:
        """Customers with a contact matching this number. [] if it isn't one."""
        number = normalize_phone(phone)
        if not number:
            return []
        return self._list("crm/v2/tenant/{t}/customers", phone=number, pageSize=10)

    def find_customers_by_name(self, name: str) -> list[dict[str, Any]]:
        name = (name or "").strip()
        if len(name) < 3:
            return []
        return self._list("crm/v2/tenant/{t}/customers", name=name, pageSize=10)

    def customer_contacts(self, customer_id: int) -> list[dict[str, Any]]:
        """The customer's contact methods: {type, value, memo}. Type is one
        of Phone, MobilePhone, Email, Fax."""
        return self._list(
            f"crm/v2/tenant/{{t}}/customers/{int(customer_id)}/contacts", pageSize=50
        )

    def memberships(
        self, customer_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """The customer's memberships. status: Active, Suspended, Expired,
        Canceled; None for every status."""
        return self._list(
            "memberships/v2/tenant/{t}/memberships",
            customerIds=str(int(customer_id)),
            status=status,
            pageSize=20,
        )

    def membership_types(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        return self._list(
            "memberships/v2/tenant/{t}/membership-types",
            ids=",".join(str(int(i)) for i in ids),
            pageSize=50,
        )

    def jobs(self, customer_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """The customer's most recently changed jobs, every status. Callers
        split open from finished with OPEN_JOB_STATUSES — one call instead
        of one per status."""
        return self._list(
            "jpm/v2/tenant/{t}/jobs",
            customerId=int(customer_id),
            sort="-ModifiedOn",
            pageSize=max(1, min(limit, 50)),
        )

    def recent_jobs(self, limit: int = 5) -> list[dict[str, Any]]:
        """The tenant's most recently changed jobs, any customer. Only
        `manage.py lookup --recent` uses this — a way to find a real customer
        to test the card on without knowing a number."""
        return self._list(
            "jpm/v2/tenant/{t}/jobs", sort="-ModifiedOn", pageSize=max(1, min(limit, 50))
        )

    def job_types(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        return self._list(
            "jpm/v2/tenant/{t}/job-types",
            ids=",".join(str(int(i)) for i in ids),
            pageSize=50,
        )

    def appointments(self, job_id: int) -> list[dict[str, Any]]:
        return self._list(
            "jpm/v2/tenant/{t}/appointments", jobId=int(job_id), pageSize=50
        )
