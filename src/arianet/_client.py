"""The Arianet API client."""

from __future__ import annotations

import ipaddress
import json
import os
import random
import socket
import time
import urllib.error
import urllib.request
import uuid
from http.client import HTTPException
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional
from urllib.parse import urlencode, urlsplit

from ._errors import APIConnectionError, APIError, ArianetError, error_from_response
from ._version import __version__
from ._wiring import attach_services

if TYPE_CHECKING:
    from ._services import (
        BaremetalService,
        CloudService,
        CoreService,
        HostingService,
        RegionalVPSService,
        SMSService,
    )

DEFAULT_BASE_URL = "https://api.ariaservice.net"
ENV_TOKEN = "ARIANET_TOKEN"
ENV_BASE_URL = "ARIANET_API_URL"
REGION_HEADER = "Arianet-Region"
_MAX_RESPONSE_BYTES = 32 << 20


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect, so the token cannot be sent to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _check_base_url(url: str) -> None:
    parts = urlsplit(url)
    if not parts.hostname:
        raise ArianetError(f"invalid base URL {url!r}")
    if parts.scheme == "https":
        return
    host = parts.hostname
    loopback = host == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if parts.scheme == "http" and loopback:
        return
    raise ArianetError(f"base URL {url!r} must use https")


class Client:
    """Client for the Arianet public API.

    Args:
        token: personal API token; ``ARIANET_TOKEN`` is read when omitted.
            Create one at https://cloud.ariaservice.net/users/api-tokens.
        base_url: API root, default ``https://api.ariaservice.net`` or ``ARIANET_API_URL``.
            Must be https (http only for localhost).
        timeout: seconds per HTTP attempt.
        max_retries: repeats after a 429, or after a network error or 502/503/504
            when the request is safe to repeat.
        max_retry_wait: longest wait in seconds before one retry; a 429 asking for
            longer raises ``RateLimitError`` at once.
        user_agent: product token appended to the User-Agent header.
    """

    core: CoreService
    cloud: CloudService
    regional_vps: RegionalVPSService
    hosting: HostingService
    baremetal: BaremetalService
    sms: SMSService

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        max_retry_wait: float = 60.0,
        user_agent: Optional[str] = None,
    ) -> None:
        self._token = token if token is not None else os.environ.get(ENV_TOKEN, "")
        self._base_url = (base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
        _check_base_url(self._base_url)
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_retry_wait = max_retry_wait
        self._user_agent = f"arianet-python/{__version__}" + (f" {user_agent}" if user_agent else "")
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._sleep: Callable[[float], None] = time.sleep
        attach_services(self)

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        body: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        idempotency_key: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Any:
        """Call any API path (including its prefix, e.g. ``/cloud/v1/servers``).

        Generated methods use this too; call it for endpoints this version does
        not have yet. Returns the decoded JSON body.
        """
        return self._send(method, path, query=query, body=body, headers=headers,
                          idempotency_key=idempotency_key, region=region, idempotent=False)

    def _send(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]],
        body: Any,
        headers: Optional[Mapping[str, str]],
        idempotency_key: Optional[str],
        region: Optional[str],
        idempotent: bool,
    ) -> Any:
        method = method.upper()
        if idempotent and not idempotency_key and method != "GET":
            idempotency_key = str(uuid.uuid4())

        url = self._base_url + path
        params = []
        for key, value in (query or {}).items():
            if value is None:
                continue
            for item in value if isinstance(value, (list, tuple)) else [value]:
                params.append((key, "true" if item is True else "false" if item is False else str(item)))
        if params:
            url += "?" + urlencode(params)

        send_headers = {k: v for k, v in (headers or {}).items()}
        if self._token:
            send_headers["Authorization"] = f"Bearer {self._token}"
        send_headers["Accept"] = "application/json"
        send_headers["User-Agent"] = self._user_agent
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            send_headers["Content-Type"] = "application/json"
        if idempotency_key:
            send_headers["Idempotency-Key"] = idempotency_key
        if region:
            send_headers[REGION_HEADER] = region

        # A network error or a 5xx is only repeated when that cannot do the work twice.
        safe = method in ("GET", "HEAD") or bool(idempotency_key)
        attempt = 0
        while True:
            try:
                return self._attempt(method, url, payload, send_headers)
            except (APIError, APIConnectionError) as exc:
                wait = self._retry_wait(exc, attempt, safe)
                if attempt >= self._max_retries or wait is None:
                    raise
                self._sleep(wait)
                attempt += 1

    def _attempt(self, method: str, url: str, payload: Optional[bytes], headers: Mapping[str, str]) -> Any:
        req = urllib.request.Request(url, data=payload, headers=dict(headers), method=method)
        try:
            resp = self._opener.open(req, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            resp = exc
        except (urllib.error.URLError, socket.timeout, OSError, HTTPException) as exc:
            raise APIConnectionError(f"request failed: {exc}") from exc
        try:
            status = resp.status if hasattr(resp, "status") and resp.status else resp.code
            raw = resp.read(_MAX_RESPONSE_BYTES)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        except (socket.timeout, OSError, HTTPException) as exc:
            raise APIConnectionError(f"request failed: {exc}") from exc
        finally:
            resp.close()

        err = error_from_response(status, resp_headers, raw)
        if err is not None:
            raise err
        if not raw.strip():
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return raw.decode("utf-8", "replace")

    def _retry_wait(self, exc: ArianetError, attempt: int, safe: bool) -> Optional[float]:
        if isinstance(exc, APIError):
            if exc.status_code == 429 or (safe and exc.status_code in (502, 503, 504)):
                wait = exc.retry_after if exc.retry_after is not None else _backoff(attempt)
                return wait if wait <= self._max_retry_wait else None
            return None
        return _backoff(attempt) if safe else None


def _backoff(attempt: int) -> float:
    base = min(8.0, 0.5 * (2 ** attempt))
    return base + random.uniform(0, base / 4)
