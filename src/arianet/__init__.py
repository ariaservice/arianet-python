"""Official Python client for the Arianet (Ariaservice) public API."""

from ._client import DEFAULT_BASE_URL, REGION_HEADER, Client
from ._error_codes import ErrorCode
from ._errors import (
    APIConnectionError,
    APIError,
    ArianetError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from ._version import __version__

__all__ = [
    "Client",
    "DEFAULT_BASE_URL",
    "REGION_HEADER",
    "ErrorCode",
    "ArianetError",
    "APIConnectionError",
    "APIError",
    "BadRequestError",
    "AuthenticationError",
    "PaymentRequiredError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "UnprocessableEntityError",
    "RateLimitError",
    "InternalServerError",
    "__version__",
]
