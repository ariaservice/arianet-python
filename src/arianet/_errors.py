"""Exceptions raised by the Arianet client."""

from __future__ import annotations

import email.utils
import json
import time
from typing import Any, Mapping, Optional


class ArianetError(Exception):
    """Base class of every exception this package raises."""


class APIConnectionError(ArianetError):
    """The request got no answer: DNS, TLS, timeout or a dropped connection."""


class APIError(ArianetError):
    """The API answered with an error.

    Attributes:
        status_code: HTTP status.
        code: the API's stable machine code, lower-cased; compare it with ``ErrorCode``.
        message: human-readable text that may change; do not branch on it.
        reason: narrows ``code`` on some refusals (e.g. ``identity_hold``), or None.
        retry_after: seconds the server asked to wait (Retry-After), or None.
        request_id: request identifier for support, when the server sent one.
        body: the decoded response body (or its text when it was not JSON).
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        reason: Optional[str] = None,
        retry_after: Optional[float] = None,
        request_id: Optional[str] = None,
        body: Any = None,
    ) -> None:
        super().__init__(f"{message} (HTTP {status_code}, code {code})")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.reason = reason
        self.retry_after = retry_after
        self.request_id = request_id
        self.body = body


class BadRequestError(APIError):
    """HTTP 400."""


class AuthenticationError(APIError):
    """HTTP 401: the token is missing, expired or revoked."""


class PaymentRequiredError(APIError):
    """HTTP 402: usually ``insufficient_balance``."""


class PermissionDeniedError(APIError):
    """HTTP 403: missing scope, IP not allowed, identity check needed..."""


class NotFoundError(APIError):
    """HTTP 404."""


class ConflictError(APIError):
    """HTTP 409."""


class UnprocessableEntityError(APIError):
    """HTTP 422: validation failed."""


class RateLimitError(APIError):
    """HTTP 429 that was still refused after the retries."""


class InternalServerError(APIError):
    """HTTP 5xx."""


_BY_STATUS = {
    400: BadRequestError,
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}

_DEFAULT_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}


def parse_retry_after(headers: Mapping[str, str], status: int) -> Optional[float]:
    """Retry-After (seconds or an HTTP date), or RateLimit-Reset on a 429."""
    value = (headers.get("retry-after") or "").strip()
    if value:
        if value.isdigit():
            return float(value)
        try:
            when = email.utils.parsedate_to_datetime(value)
            return max(0.0, when.timestamp() - time.time())
        except (TypeError, ValueError):
            pass
    if status == 429:
        reset = (headers.get("ratelimit-reset") or "").strip()
        if reset.isdigit() and int(reset) > 0:
            return float(reset)
    return None


def error_from_response(status: int, headers: Mapping[str, str], raw: bytes) -> Optional[APIError]:
    """The APIError a response stands for, or None.

    Reads the three error shapes the APIs use::

        {"success": false, "error": {"code": "...", "message": "..."}}   core API
        {"error": "message", "code": "...", "reason": "..."}             cloud API
        {"code": "...", "message": "..."}                                product APIs
    """
    try:
        data: Any = json.loads(raw.decode("utf-8")) if raw.strip() else None
        decoded = True
    except (ValueError, UnicodeDecodeError):
        data = raw.decode("utf-8", "replace")
        decoded = False
    obj = data if isinstance(data, dict) else {}
    failed = status >= 300 or obj.get("success") is False
    if not failed:
        return None

    code = obj.get("code") if isinstance(obj.get("code"), str) else None
    message = obj.get("message") if isinstance(obj.get("message"), str) else None
    reason = obj.get("reason") if isinstance(obj.get("reason"), str) else None
    err = obj.get("error")
    if isinstance(err, str):
        message = err
    elif isinstance(err, dict):
        code = err.get("code") or code
        message = err.get("message") or message
        reason = err.get("reason") or reason
    if not code:
        code = _DEFAULT_CODES.get(status, "request_failed") if decoded else "unexpected_response"
    if not message:
        message = f"request failed with HTTP {status}"

    cls = _BY_STATUS.get(status) or (InternalServerError if status >= 500 else APIError)
    return cls(
        status,
        str(code).lower(),
        message,
        reason=reason,
        retry_after=parse_retry_after(headers, status),
        request_id=headers.get("x-request-id") or headers.get("request-id"),
        body=data,
    )
