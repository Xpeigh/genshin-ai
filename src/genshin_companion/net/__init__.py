"""Outbound networking. Everything here is re-exported from ``client``; nothing else may do I/O."""

from genshin_companion.net.client import (
    HostNotAllowedError,
    HttpResponse,
    NetworkError,
    NetworkPolicy,
    NetworkTimeoutError,
    PolicyViolationError,
    RedirectNotAllowedError,
    ResponseTooLargeError,
    SafeHttpClient,
)

__all__ = [
    "HostNotAllowedError",
    "HttpResponse",
    "NetworkError",
    "NetworkPolicy",
    "NetworkTimeoutError",
    "PolicyViolationError",
    "RedirectNotAllowedError",
    "ResponseTooLargeError",
    "SafeHttpClient",
]
