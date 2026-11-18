"""Fast security-boundary regressions that do not require PostgreSQL."""

import base64
from datetime import UTC, datetime
import json
import time

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security_identity import issue_access_token, totp_code
from app.models import SecuritySession, User

pytestmark = pytest.mark.no_database


@pytest.mark.parametrize("timestamp,expected", [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
    (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130"),
])
def test_totp_matches_rfc_6238_sha1_vectors(timestamp: int, expected: str) -> None:
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp_code(secret, timestamp) == expected


def _settings(*, enforced: bool) -> Settings:
    return Settings(
        cerebras_api_key="x",
        searchapi_api_key="x",
        tavily_api_key="x",
        database_url="postgresql+asyncpg://localhost/travel_agent_test",
        zero_trust_enforced=enforced,
        zero_trust_signing_secret="x" * 32,
    )


def test_access_token_expiry_is_utc_on_a_non_utc_server(monkeypatch: pytest.MonkeyPatch) -> None:
    expires_at = datetime(2030, 1, 1, 12, 0)
    security_session = SecuritySession(
        user_id=1,
        tenant_id="tenant-a",
        device_id="device-a",
        expires_at=expires_at,
    )
    user = User(id=1, email="traveler@example.test")
    monkeypatch.setattr("app.config.get_settings", lambda: _settings(enforced=True))
    monkeypatch.setenv("TZ", "PST8PDT")
    time.tzset()
    try:
        token = issue_access_token(security_session, user)
    finally:
        monkeypatch.undo()
        time.tzset()

    payload = token.split(".", 1)[0]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    assert claims["expires_at"] == int(expires_at.replace(tzinfo=UTC).timestamp())


@pytest.mark.parametrize(
    "field_name,error_message",
    [
        ("zero_trust_signing_secret", "at least 32 bytes"),
        ("device_gateway_secret", "DEVICE_GATEWAY_SECRET"),
    ],
)
def test_security_secrets_require_32_bytes(field_name: str, error_message: str) -> None:
    settings = {
        "cerebras_api_key": "x",
        "searchapi_api_key": "x",
        "tavily_api_key": "x",
        "database_url": "postgresql+asyncpg://localhost/travel_agent_test",
        "zero_trust_enforced": True,
        "zero_trust_signing_secret": "x" * 32,
    }
    settings[field_name] = "x" * 31
    with pytest.raises(ValidationError, match=error_message):
        Settings(**settings)


def test_runtime_configuration_cannot_disable_security(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZERO_TRUST_ENFORCED", "false")
    with pytest.raises(ValidationError, match="cannot be disabled"):
        Settings(
            _env_file=None,
            cerebras_api_key="x", searchapi_api_key="x", tavily_api_key="x",
            database_url="postgresql+asyncpg://localhost/travel_agent_test",
        )
