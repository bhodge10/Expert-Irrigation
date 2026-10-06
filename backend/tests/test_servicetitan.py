"""The ServiceTitan client, against a fake transport. Nothing here reaches
the real service — conftest blanks the credentials, and every client built
below carries a MockTransport."""

import httpx
import pytest

from app.config import settings
from app.servicetitan import (
    SCOPES,
    ServiceTitanClient,
    ServiceTitanError,
    find_phones,
    normalize_phone,
)

TOKEN = {"access_token": "tok", "expires_in": 900}
EMPTY_PAGE = {"page": 1, "pageSize": 1, "hasMore": False, "totalCount": 0, "data": []}


def make_client(handler, **kwargs) -> ServiceTitanClient:
    return ServiceTitanClient(
        app_key="app-key",
        tenant_id="123",
        client_id="cid",
        client_secret="secret",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def is_token_request(request: httpx.Request) -> bool:
    return request.url.host.startswith("auth")


def test_one_token_serves_many_calls_and_every_call_is_signed():
    seen = {"tokens": 0, "calls": []}

    def handler(request):
        if is_token_request(request):
            seen["tokens"] += 1
            assert request.url.path == "/connect/token"
            body = request.content.decode()
            assert "grant_type=client_credentials" in body
            assert "client_id=cid" in body and "client_secret=secret" in body
            return httpx.Response(200, json=TOKEN)
        seen["calls"].append(request)
        return httpx.Response(200, json=EMPTY_PAGE)

    with make_client(handler) as st:
        st.find_customers_by_phone("(859) 555-0100")
        st.job_types([7])

    assert seen["tokens"] == 1
    assert len(seen["calls"]) == 2
    for request in seen["calls"]:
        assert request.headers["ST-App-Key"] == "app-key"
        assert request.headers["Authorization"] == "Bearer tok"

    customers = seen["calls"][0]
    assert customers.url.host == "api.servicetitan.io"
    assert customers.url.path == "/crm/v2/tenant/123/customers"
    assert customers.url.params["phone"] == "8595550100"


def test_bad_credentials_name_the_variables_to_check():
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_client"})

    with make_client(handler) as st:
        with pytest.raises(ServiceTitanError) as exc:
            st.check_token()
    assert "SERVICETITAN_CLIENT_ID" in str(exc.value)
    assert exc.value.status == 400


def test_a_rejected_token_is_replaced_once():
    seen = {"tokens": 0, "calls": 0}

    def handler(request):
        if is_token_request(request):
            seen["tokens"] += 1
            return httpx.Response(200, json=TOKEN)
        seen["calls"] += 1
        if seen["calls"] == 1:
            return httpx.Response(401)
        return httpx.Response(200, json=EMPTY_PAGE)

    with make_client(handler) as st:
        assert st.job_types([1]) == []
    assert seen["tokens"] == 2
    assert seen["calls"] == 2


def test_probe_reads_every_scope_and_names_the_denied_ones():
    def handler(request):
        if is_token_request(request):
            return httpx.Response(200, json=TOKEN)
        assert request.url.params["pageSize"] == "1"
        assert request.url.params["includeTotal"] == "true"
        if request.url.path.startswith("/memberships/"):
            return httpx.Response(403, text="forbidden")
        return httpx.Response(200, json={**EMPTY_PAGE, "totalCount": 42})

    with make_client(handler) as st:
        results = st.probe()

    assert [r.scope for r in results] == [scope for scope, _ in SCOPES]
    by_scope = {r.scope: r for r in results}
    assert by_scope["Customers"].ok and by_scope["Customers"].total == 42
    assert not by_scope["Customer Memberships"].ok
    assert by_scope["Customer Memberships"].detail.startswith("DENIED")
    assert not by_scope["Membership Types"].ok


def test_lookup_paths_and_parameters():
    seen = []

    def handler(request):
        if is_token_request(request):
            return httpx.Response(200, json=TOKEN)
        seen.append(request)
        return httpx.Response(200, json={**EMPTY_PAGE, "data": [{"id": 1}]})

    with make_client(handler) as st:
        assert st.customer_contacts(55) == [{"id": 1}]
        st.memberships(55, status="Active")
        st.membership_types([3, 4])
        st.jobs(55)
        st.appointments(900)
        st.recent_jobs(limit=3)
        st.recent_jobs(limit=3, status="Scheduled")
        st.recent_memberships(limit=4)
        st.customer(77)
        assert st.find_customers_by_name("Jo") == []  # too short to ask
        assert st.find_customers_by_phone("not a number") == []

    paths = [r.url.path for r in seen]
    assert paths == [
        "/crm/v2/tenant/123/customers/55/contacts",
        "/memberships/v2/tenant/123/memberships",
        "/memberships/v2/tenant/123/membership-types",
        "/jpm/v2/tenant/123/jobs",
        "/jpm/v2/tenant/123/appointments",
        "/jpm/v2/tenant/123/jobs",
        "/jpm/v2/tenant/123/jobs",
        "/memberships/v2/tenant/123/memberships",
        "/crm/v2/tenant/123/customers/77",
    ]
    assert seen[1].url.params["customerIds"] == "55"
    assert seen[1].url.params["status"] == "Active"
    assert seen[2].url.params["ids"] == "3,4"
    assert seen[3].url.params["customerId"] == "55"
    assert seen[3].url.params["sort"] == "-ModifiedOn"
    assert seen[4].url.params["jobId"] == "900"
    assert seen[5].url.params["sort"] == "-ModifiedOn"
    assert seen[5].url.params["pageSize"] == "3"
    assert "customerId" not in seen[5].url.params
    assert "jobStatus" not in seen[5].url.params
    assert seen[6].url.params["jobStatus"] == "Scheduled"
    assert seen[7].url.params["status"] == "Active"
    assert "customerIds" not in seen[7].url.params


def test_a_failed_read_raises_with_the_status():
    def handler(request):
        if is_token_request(request):
            return httpx.Response(200, json=TOKEN)
        return httpx.Response(404, text="nope")

    with make_client(handler) as st:
        with pytest.raises(ServiceTitanError) as exc:
            st.jobs(1)
    assert exc.value.status == 404


def test_integration_environment_uses_the_sandbox_hosts():
    def handler(request):
        return httpx.Response(200, json=TOKEN)

    with make_client(handler, environment="integration") as st:
        assert st.api_base == "https://api-integration.servicetitan.io"
        assert st.token_url == "https://auth-integration.servicetitan.io/connect/token"

    with pytest.raises(ValueError):
        make_client(handler, environment="staging")


def test_settings_need_all_four_values(monkeypatch):
    assert not settings.servicetitan_configured
    monkeypatch.setattr(settings, "servicetitan_app_key", "k")
    monkeypatch.setattr(settings, "servicetitan_tenant_id", "1")
    monkeypatch.setattr(settings, "servicetitan_client_id", "c")
    assert not settings.servicetitan_configured
    monkeypatch.setattr(settings, "servicetitan_client_secret", "s")
    assert settings.servicetitan_configured


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("(859) 282-8101", "8592828101"),
        ("859.282.8101", "8592828101"),
        ("+1 859 282 8101", "8592828101"),
        ("18592828101", "8592828101"),
        ("282-8101", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_find_phones_pulls_numbers_out_of_a_message():
    text = (
        "Call me at (859) 282-8101 or 859.555.0100.\n"
        "Cell: +1 859 555 0101. Order 12345678901234 shipped.\n"
        "Again: 859-282-8101."
    )
    assert find_phones(text) == ["8592828101", "8595550100", "8595550101"]
    assert find_phones("") == []
    assert find_phones(None) == []
