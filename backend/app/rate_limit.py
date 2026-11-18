"""Rate limiting for quota-spending routes."""

import time

from fastapi import Request

from app.config import (
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)
from app.security_device import verified_device_id
from app.schemas import ErrorCode, LoginRequest

_request_timestamps: dict[str, list[float]] = {}


class RateLimitError(Exception):
    """A domain rejection carrying the client-facing code, detail, and Retry-After seconds."""

    def __init__(self, code: ErrorCode, detail: str, retry_after_seconds: int) -> None:
        self.code = code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)


def _enforce_rate_limit(key: str) -> None:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS

    # ponytail: O(active keys) cleanup; use a shared limiter when one process is no longer enough.
    for existing_key, timestamps in list(_request_timestamps.items()):
        recent_timestamps = [timestamp for timestamp in timestamps if timestamp > window_start]
        if recent_timestamps:
            _request_timestamps[existing_key] = recent_timestamps
        else:
            del _request_timestamps[existing_key]

    recent = _request_timestamps.get(key, [])
    if len(recent) >= RATE_LIMIT_MAX_REQUESTS:
        raise RateLimitError(
            ErrorCode.RATE_LIMIT_EXCEEDED,
            f"Rate limit exceeded: max {RATE_LIMIT_MAX_REQUESTS} requests per "
            f"{RATE_LIMIT_WINDOW_SECONDS}s from this client on this route.",
            retry_after_seconds=RATE_LIMIT_WINDOW_SECONDS,
        )
    recent.append(now)
    _request_timestamps[key] = recent


def _client_key(request: Request) -> str:
    device_id = verified_device_id(request)
    if device_id is not None:
        return f"device:{device_id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


async def enforce_request_rate_limit(request: Request) -> None:
    _enforce_rate_limit(_client_key(request))


async def enforce_login_rate_limit(body: LoginRequest, request: Request) -> None:
    client_key = _client_key(request)
    _enforce_rate_limit(f"login-client:{client_key}")
    _enforce_rate_limit(f"login-account:{body.email.strip().casefold()}")
