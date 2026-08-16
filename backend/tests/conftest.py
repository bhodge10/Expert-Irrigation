"""Shared test guardrails.

Settings load from the real .env, which on a configured machine holds live
Microsoft and Anthropic credentials. Tests must never touch either service —
this blanks the credentials for every test, whatever the machine has. Tests
that exercise "configured" code paths set a fake key explicitly.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def no_real_apis(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(settings, "ms_tenant_id", "", raising=False)
    monkeypatch.setattr(settings, "ms_client_id", "", raising=False)
    monkeypatch.setattr(settings, "ms_client_secret", "", raising=False)
