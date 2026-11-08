"""The ONLY way bytes leave this process.

Security contract (see SPEC.md, "Security and privacy"):

* ``GET`` and ``HEAD`` only. There is deliberately no method that can send a request body.
* HTTPS only, default port only, no URL credentials, no IP literals.
* The target host must be in an explicit allowlist (exact match, no wildcards, no subdomain
  inheritance). The same check is re-applied to every redirect hop; redirects are followed by this
  module, never by the HTTP library.
* No cookies, no credentials, no ambient proxy/netrc configuration (``trust_env=False``).
  Callers may only add a few conditional-request headers.
* Hard size caps measured on *decoded* bytes, connect/read timeouts and a total deadline.
* URLs are never logged and never placed in exception messages: they can contain a UID.

``tests/test_architecture.py`` fails the build if any other module imports an HTTP library, so this
guarantee cannot rot. Do not add request-body support here without updating SPEC.md and Ben.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Final
from urllib.parse import urljoin, urlsplit

import httpx

from genshin_companion import __version__

_log = logging.getLogger("genshin_companion.net")

# httpx logs full request URLs at INFO, which would leak UIDs into user log files. A level set once
# at import can be undone by later logging configuration, so we also attach a filter and re-assert
# both every time a client is built.
_QUIET_LOGGERS: Final = (
    "httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    "httpcore.proxy", "httpcore.socks", "hpack", "h2", "h11",
)  # fmt: skip


class _DropBelowWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


_QUIET_FILTER: Final = _DropBelowWarning()


def _silence_library_logging() -> None:
    for name in _QUIET_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        if _QUIET_FILTER not in logger.filters:
            logger.addFilter(_QUIET_FILTER)


_silence_library_logging()

_HOST_RE: Final = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_MAX_URL_LEN: Final = 2048
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
# Only conditional-request headers may be supplied by callers. Anything credential-like is refused.
_ALLOWED_EXTRA_HEADERS: Final = frozenset({"if-none-match", "if-modified-since", "accept"})
_DROPPED_RESPONSE_HEADERS: Final = frozenset({"set-cookie", "set-cookie2"})


class NetworkError(Exception):
    """Base class. Messages never contain URLs."""


class PolicyViolationError(NetworkError):
    """The request was refused locally; nothing was sent."""


class HostNotAllowedError(PolicyViolationError):
    """The host is not in the allowlist."""


class RedirectNotAllowedError(PolicyViolationError):
    """A redirect pointed outside the policy, or redirects were malformed/too many."""


class ResponseTooLargeError(NetworkError):
    """The response body exceeded the size cap."""


class NetworkTimeoutError(NetworkError):
    """Connect/read timeout or total deadline exceeded."""


def _validate_allowlist_host(host: str) -> None:
    # The last label must start with a letter: "127.1", "0x7f.1" and "10.1" are IP literals to the
    # OS resolver even though ipaddress.ip_address() does not recognise them.
    if not _HOST_RE.fullmatch(host) or not host.rsplit(".", 1)[1][0].isalpha():
        msg = "invalid allowlist entry (need a lowercase DNS name with a dot, no wildcard/scheme)"
        raise ValueError(msg)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return
    msg = "invalid allowlist entry (IP addresses are not allowed)"
    raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    allowed_hosts: frozenset[str]
    max_redirects: int = 3
    default_max_bytes: int = 5 * 1024 * 1024
    hard_max_bytes: int = 64 * 1024 * 1024
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    total_timeout: float = 45.0
    user_agent: str = field(
        default=f"GenshinCompanion/{__version__} (unofficial fan tool; local-first; no telemetry)"
    )

    def __post_init__(self) -> None:
        if isinstance(self.allowed_hosts, str):
            msg = "allowed_hosts must be a collection of host names, not a string (allowlist)"
            raise ValueError(msg)
        # Own an immutable copy so a caller's mutable set cannot widen the allowlist later.
        object.__setattr__(self, "allowed_hosts", frozenset(self.allowed_hosts))
        for host in self.allowed_hosts:
            _validate_allowlist_host(host)
        if not (0 <= self.max_redirects <= 10):
            msg = "max_redirects must be between 0 and 10"
            raise ValueError(msg)
        if not (0 < self.default_max_bytes <= self.hard_max_bytes):
            msg = "default_max_bytes must be positive and <= hard_max_bytes"
            raise ValueError(msg)
        if min(self.connect_timeout, self.read_timeout, self.total_timeout) <= 0:
            msg = "timeouts must be positive"
            raise ValueError(msg)
        if not self.user_agent.isascii() or not self.user_agent.isprintable():
            msg = "user_agent must be printable ASCII"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes


def _split_checked(url: str) -> tuple[str, str]:
    """Return (normalised host, rebuilt https URL) or raise PolicyViolationError."""
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_LEN:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise PolicyViolationError("URL is empty, not a string, or too long")
    if any(ord(c) <= 0x20 or ord(c) == 0x7F or c == "\\" for c in url):
        raise PolicyViolationError("URL contains whitespace, control or backslash characters")
    # Parser errors embed the authority text (userinfo/port), so raise OUTSIDE the except block to
    # leave no __cause__/__context__ carrying it into a caller's log.
    parts = None
    port = None
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        parts = None
    if parts is None:
        raise PolicyViolationError("URL could not be parsed")
    if parts.netloc.endswith(":"):
        raise PolicyViolationError("explicit ports are not allowed")
    if parts.scheme != "https":
        raise PolicyViolationError("only https URLs are allowed")
    if "@" in parts.netloc:
        raise PolicyViolationError("URL credentials are not allowed")
    if port is not None:
        raise PolicyViolationError("explicit ports are not allowed")
    raw_host = parts.hostname
    if not raw_host:
        raise PolicyViolationError("URL has no host")
    host = raw_host.rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PolicyViolationError("IP address hosts are not allowed")
    if not host.isascii():
        ascii_host = None
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            ascii_host = None
        if ascii_host is None:
            raise PolicyViolationError("host is not valid IDNA")
        host = ascii_host
    rebuilt = f"https://{host}{parts.path or '/'}"
    if parts.query:
        rebuilt += f"?{parts.query}"
    return host, rebuilt


class SafeHttpClient:
    """GET/HEAD-only, allowlisted, size-capped HTTP client. See module docstring."""

    def __init__(
        self, policy: NetworkPolicy, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._policy = policy
        _silence_library_logging()
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,  # we follow redirects ourselves, re-checking the allowlist
            trust_env=False,  # no HTTP(S)_PROXY, netrc or SSL_CERT_* surprises
            http2=False,
            timeout=httpx.Timeout(
                connect=policy.connect_timeout,
                read=policy.read_timeout,
                write=policy.read_timeout,
                pool=policy.connect_timeout,
            ),
            headers={"User-Agent": policy.user_agent, "Accept-Encoding": "identity"},
        )

    # -- lifecycle ----------------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SafeHttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- public API: the only two verbs -------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        max_bytes: int | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        return self._fetch("GET", url, max_bytes, extra_headers)

    def head(self, url: str, *, extra_headers: Mapping[str, str] | None = None) -> HttpResponse:
        return self._fetch("HEAD", url, None, extra_headers)

    # -- internals ----------------------------------------------------------------------------

    def _check_host(self, host: str) -> None:
        if host not in self._policy.allowed_hosts:
            raise HostNotAllowedError("host is not in the allowlist")

    def _check_headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in (extra or {}).items():
            if key.lower() not in _ALLOWED_EXTRA_HEADERS:
                raise PolicyViolationError("header is not permitted")
            if any(c in key + value for c in "\r\n\0"):
                raise PolicyViolationError("header contains control characters")
            out[key] = value
        return out

    def _fetch(
        self,
        method: str,
        url: str,
        max_bytes: int | None,
        extra_headers: Mapping[str, str] | None,
    ) -> HttpResponse:
        policy = self._policy
        cap = policy.default_max_bytes if max_bytes is None else max_bytes
        if cap <= 0 or cap > policy.hard_max_bytes:
            raise PolicyViolationError("max_bytes is outside the permitted range")
        headers = self._check_headers(extra_headers)
        deadline = time.monotonic() + policy.total_timeout

        host, current = _split_checked(url)
        self._check_host(host)
        first_host = host

        for hop in range(policy.max_redirects + 1):
            hop_headers = headers if host == first_host else {}
            resp = self._send_once(method, current, hop_headers, cap, deadline)
            if resp.status not in _REDIRECT_STATUSES:
                return resp
            location = resp.headers.get("location")
            if not location:
                raise RedirectNotAllowedError("redirect without a Location header")
            if hop == policy.max_redirects:
                raise RedirectNotAllowedError("too many redirects")
            try:
                host, current = _split_checked(urljoin(current, location))
                self._check_host(host)
            except PolicyViolationError as exc:
                raise RedirectNotAllowedError("redirect target violates the policy") from exc
        raise RedirectNotAllowedError("too many redirects")  # pragma: no cover

    def _send_once(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        cap: int,
        deadline: float,
    ) -> HttpResponse:
        """One request. Failures are recorded inside ``try`` and raised AFTER it, so no exception
        carries an httpx exception (which can embed the URL) as ``__cause__`` or ``__context__``."""
        failure: NetworkError | None = None
        result: HttpResponse | None = None
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = NetworkTimeoutError("total request deadline exceeded")
            else:
                result, failure = self._exchange(method, url, headers, cap, deadline, remaining)
        except httpx.TimeoutException:
            failure = NetworkTimeoutError("request timed out")
        except httpx.InvalidURL:
            failure = PolicyViolationError("URL rejected by the HTTP library")
        except httpx.HTTPError as exc:
            # Only the exception class name is kept: httpx messages can embed the full URL.
            failure = NetworkError(f"network error ({type(exc).__name__})")
        if failure is not None:
            raise failure
        assert result is not None
        return result

    def _exchange(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        cap: int,
        deadline: float,
        remaining: float,
    ) -> tuple[HttpResponse | None, NetworkError | None]:
        policy = self._policy
        # No single blocking read may outlive the total deadline.
        timeout = httpx.Timeout(
            connect=min(policy.connect_timeout, remaining),
            read=min(policy.read_timeout, remaining),
            write=min(policy.read_timeout, remaining),
            pool=min(policy.connect_timeout, remaining),
        )
        request = self._client.build_request(method, url, headers=headers, timeout=timeout)
        resp = self._client.send(request, stream=True)
        try:
            # Never keep cookies between requests, even though we never send any.
            self._client.cookies.clear()
            status = resp.status_code
            is_redirect = status in _REDIRECT_STATUSES
            body_wanted = method != "HEAD" and not is_redirect
            encoding = resp.headers.get("content-encoding", "identity").strip().lower()
            if body_wanted and encoding not in {"", "identity"}:
                # We ask for identity so the cap is on wire bytes. A server that compresses anyway
                # could expand to unbounded memory, so the body is refused rather than decoded.
                return None, NetworkError("server used an unrequested content-encoding")
            declared = resp.headers.get("content-length")
            if body_wanted and declared is not None:
                if not declared.isdigit():
                    return None, NetworkError("malformed Content-Length header")
                if len(declared) > 18 or int(declared) > cap:
                    return None, ResponseTooLargeError("declared Content-Length exceeds the cap")
            chunks: list[bytes] = []
            total = 0
            if body_wanted:
                # iter_raw yields per network read (no decoding, no re-chunking buffer), so the
                # size and deadline checks run on every read.
                for chunk in resp.iter_raw():
                    total += len(chunk)
                    if total > cap:
                        return None, ResponseTooLargeError("response body exceeds the cap")
                    chunks.append(chunk)
                    if time.monotonic() > deadline:
                        return None, NetworkTimeoutError("total request deadline exceeded")
            out_headers = {
                k.lower(): v
                for k, v in resp.headers.items()
                if k.lower() not in _DROPPED_RESPONSE_HEADERS
            }
            _log.debug("response status=%s host=%s", status, resp.url.host)
            return HttpResponse(url, status, out_headers, b"".join(chunks)), None
        finally:
            resp.close()
