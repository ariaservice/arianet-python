"""Base class of the generated API groups."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Mapping, Optional
from urllib.parse import quote

if TYPE_CHECKING:
    from ._client import Client


def path_segment(value: Any) -> str:
    return quote(str(value), safe="")


class Service:
    _prefix = ""

    def __init__(self, client: Client, region: Optional[str] = None) -> None:
        self._client = client
        self._region = region

    def with_region(self, region: Optional[str]):
        """A copy of this API group whose requests go to ``region`` (the Arianet-Region header)."""
        clone = copy.copy(self)
        clone._region = region
        return clone

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]],
        body: Any,
        idempotent: bool,
        idempotency_key: Optional[str],
        headers: Optional[Mapping[str, str]],
    ) -> Any:
        return self._client._send(
            method,
            path,
            query=query,
            body=body,
            headers=headers,
            idempotency_key=idempotency_key,
            region=self._region,
            idempotent=idempotent,
        )
