"""Application configuration, loaded once from the environment (fail-fast).

Secrets are wrapped in ``SecretStr`` so they never appear in logs or ``repr`` output.
Every tunable the automation and adapters rely on lives here as a named constant; no magic
numbers scattered through the codebase.
"""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


SEARCHAPI_BASE_URL = "https://www.searchapi.io/api/v1/search"
SEARCHAPI_TIMEOUT_SECONDS = 60.0

SLACK_API_TIMEOUT_SECONDS = 10.0

# RecordedProvider replays real-captured payloads from here; never hand-fabricated.
FLIGHT_CASSETTE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "recorded" / "flights"

# A flight offer is only bookable for a short window because airfares are volatile. After this,
# the booking is marked EXPIRED and the user must re-search rather than book a stale price.
BOOKING_TTL_MINUTES = 30

# Reuse a real flight search for the same route+dates for this long instead of spending another
# unit of the scarce one-time 100-search SearchApi quota. Deliberately short relative to that
# quota concern: flight prices reprice multiple times a day, and a cached result must not
# outlive BOOKING_TTL_MINUTES (30) by much, or a "fresh" search could already hand out a token
# that's dead by the time a human confirms it. A renewable-quota production deployment should
# revalidate even more often than this.
FLIGHT_CACHE_TTL_MINUTES = 15

# The identity fallback is used only when security enforcement is disabled for development.
DEMO_USER_EMAIL = "tonytrieu.dev@gmail.com"

# Per-client request cap on the flight-search route.
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    searchapi_api_key: SecretStr
    database_url: str

    use_live_flight_api: bool = True
    frontend_origin: str = "http://localhost:5173"
    # Retained so old deployments fail startup instead of silently accepting an unsafe setting.
    zero_trust_enforced: bool = True
    # No explicit secret -> a fresh per-process key, so an out-of-the-box run is enforced AND
    # unforgeable (nothing in the repo can sign a valid token). A real deployment sets an explicit
    # secret so tokens survive a restart and are shared across processes.
    zero_trust_signing_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(32))
    )

    device_gateway_secret: SecretStr | None = None

    slack_bot_token: SecretStr | None = None
    slack_signing_secret: SecretStr | None = None
    slack_approvals_channel_id: str | None = None

    # No DSN -> Sentry stays off, so local runs and tests need no Sentry project.
    sentry_dsn: SecretStr | None = None
    @computed_field
    @property
    def dbos_database_url(self) -> str:
        """DBOS speaks the plain (psycopg/sync) Postgres URL, not the asyncpg dialect."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @model_validator(mode="after")
    def _reject_weak_signing_secret(self) -> "Settings":
        if not self.zero_trust_enforced:
            raise ValueError("Security enforcement cannot be disabled")
        signing_secret = self.zero_trust_signing_secret.get_secret_value()
        if self.zero_trust_enforced and len(signing_secret.encode()) < 32:
            raise ValueError(
                "ZERO_TRUST_SIGNING_SECRET must be at least 32 bytes when "
                "ZERO_TRUST_ENFORCED is enabled"
            )
        if self.device_gateway_secret is not None and len(self.device_gateway_secret.get_secret_value().encode()) < 32:
            raise ValueError(
                "DEVICE_GATEWAY_SECRET must be at least 32 bytes when configured"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Fails loudly at startup if a required key is missing, rather than at the first request.
    """
    return Settings()  # pyright: ignore[reportCallIssue]  # values come from the environment
