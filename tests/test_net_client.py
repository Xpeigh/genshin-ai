"""Behavioural tests for the one-and-only outbound HTTP client. No live network: MockTransport."""

from __future__ import annotations

import gzip
import logging
from collections.abc import Callable

import httpx
import pytest

from genshin_companion.net import (
    HostNotAllowedError,
    NetworkError,
    NetworkPolicy,
    NetworkTimeoutError,
    PolicyViolationError,
    RedirectNotAllowedError,
    ResponseTooLargeError,
    SafeHttpClient,
)
from helpers import StreamingTransport

ALLOWED = "api.allowed.test"
OTHER = "other.allowed.test"


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    hosts: tuple[str, ...] = (ALLOWED, OTHER),
    **policy_kwargs: object,
) -> SafeHttpClient:
    policy = NetworkPolicy(allowed_hosts=frozenset(hosts), **policy_kwargs)  # type: ignore[arg-type]
    return SafeHttpClient(policy, transport=StreamingTransport(handler))


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"hello", headers={"content-type": "text/plain"})


# --- happy path ------------------------------------------------------------------------------


def test_get_allowed_host_returns_body_and_status() -> None:
    with make_client(ok) as client:
        resp = client.get(f"https://{ALLOWED}/x")
    assert resp.status == 200
    assert resp.body == b"hello"
    assert resp.headers["content-type"] == "text/plain"
    assert resp.url == f"https://{ALLOWED}/x"


def test_head_is_supported_and_has_no_body() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.method)
        return httpx.Response(200, headers={"etag": '"abc"'})

    with make_client(handler) as client:
        resp = client.head(f"https://{ALLOWED}/x")
    assert seen == ["HEAD"]
    assert resp.body == b""
    assert resp.headers["etag"] == '"abc"'


def test_non_2xx_is_returned_not_raised_so_callers_can_read_retry_after() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "30"})

    with make_client(handler) as client:
        resp = client.get(f"https://{ALLOWED}/x")
    assert resp.status == 429
    assert resp.headers["retry-after"] == "30"


def test_host_matching_is_case_insensitive_and_ignores_trailing_dot() -> None:
    with make_client(ok) as client:
        assert client.get("https://API.Allowed.TEST./x").status == 200


# --- the client can only GET/HEAD ------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["post", "put", "patch", "delete", "request", "send", "stream", "options"]
)
def test_no_other_http_verbs_exist(name: str) -> None:
    with make_client(ok) as client:
        assert not hasattr(client, name)


# --- request hygiene -------------------------------------------------------------------------


def test_sends_descriptive_user_agent_and_no_credentials_or_cookies() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, headers={"set-cookie": "sid=secret; Path=/"})

    with make_client(handler, user_agent="TestApp/1.0 (+unofficial)") as client:
        client.get(f"https://{ALLOWED}/a")
        client.get(f"https://{ALLOWED}/b")
    for req in captured:
        assert req.headers["user-agent"] == "TestApp/1.0 (+unofficial)"
        assert "cookie" not in req.headers
        assert "authorization" not in req.headers
        assert req.content == b""


@pytest.mark.parametrize("header", ["Authorization", "Cookie", "Proxy-Authorization", "X-Api-Key"])
def test_credential_headers_cannot_be_added(header: str) -> None:
    with make_client(ok) as client, pytest.raises(PolicyViolationError):
        client.get(f"https://{ALLOWED}/x", extra_headers={header: "x"})


def test_conditional_request_headers_are_allowed() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(304)

    with make_client(handler) as client:
        resp = client.get(f"https://{ALLOWED}/x", extra_headers={"If-None-Match": '"abc"'})
    assert resp.status == 304
    assert captured[0].headers["if-none-match"] == '"abc"'


def test_urls_are_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with make_client(ok) as client:
        client.get(f"https://{ALLOWED}/api/uid/800123456?secret=1")
    assert "800123456" not in caplog.text
    assert "secret" not in caplog.text


# --- URL policy ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"http://{ALLOWED}/x",  # not https
        "ftp://api.allowed.test/x",
        "file:///etc/passwd",
        "//api.allowed.test/x",
        "data:text/plain,hi",
        f"https://user:pw@{ALLOWED}/x",  # userinfo
        f"https://{ALLOWED}:8443/x",  # non-default port
        f"https://{ALLOWED}:443/x",  # explicit port: keep the rule simple, reject
        "https://127.0.0.1/x",  # IP literal
        "https://[::1]/x",
        "https://10.0.0.1/x",
        "https://localhost/x",
        "https://evil.test/x",  # not in allowlist
        f"https://sub.{ALLOWED}/x",  # subdomain of allowed != allowed
        f"https://{ALLOWED}.evil.test/x",  # allowed as prefix
        f"https://evil{ALLOWED}/x",  # allowed as suffix without dot
        f"https://{ALLOWED}@evil.test/x",  # userinfo trick
        f"https://evil.test\\@{ALLOWED}/x",  # backslash trick
        f"https://{ALLOWED}/x y",  # whitespace
        f"https://{ALLOWED}/x\r\nHost: evil.test",  # CRLF
        f"https://{ALLOWED}/\x00",
        "",
        "not a url",
    ],
)
def test_bad_urls_rejected_before_any_request(url: str) -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    with make_client(handler) as client, pytest.raises(PolicyViolationError):
        client.get(url)
    assert called is False


def test_host_not_allowed_has_specific_error_type() -> None:
    with make_client(ok) as client, pytest.raises(HostNotAllowedError):
        client.get("https://evil.test/x")


@pytest.mark.parametrize(
    "host", ["*.example.com", "http://x.test", "1.2.3.4", "a/b", "", "Ex ample"]
)
def test_invalid_allowlist_entries_are_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="allow"):
        NetworkPolicy(allowed_hosts=frozenset({host}))


def test_empty_allowlist_blocks_everything() -> None:
    with make_client(ok, hosts=()) as client, pytest.raises(HostNotAllowedError):
        client.get(f"https://{ALLOWED}/x")


# --- redirects -------------------------------------------------------------------------------


def test_redirect_within_allowlist_is_followed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == ALLOWED:
            return httpx.Response(302, headers={"location": f"https://{OTHER}/final"})
        return httpx.Response(200, content=b"done")

    with make_client(handler) as client:
        resp = client.get(f"https://{ALLOWED}/start")
    assert resp.body == b"done"
    assert resp.url == f"https://{OTHER}/final"


def test_relative_redirect_is_followed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/start":
            return httpx.Response(301, headers={"location": "/moved"})
        return httpx.Response(200, content=b"moved")

    with make_client(handler) as client:
        assert client.get(f"https://{ALLOWED}/start").body == b"moved"


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.test/x",
        "http://api.allowed.test/x",  # downgrade
        "ftp://api.allowed.test/x",
        "https://user@api.allowed.test/x",
        "//evil.test/x",  # scheme-relative
    ],
)
def test_redirect_out_of_policy_is_blocked(location: str) -> None:
    hits: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(str(req.url.host))
        return httpx.Response(302, headers={"location": location})

    with make_client(handler) as client, pytest.raises(RedirectNotAllowedError):
        client.get(f"https://{ALLOWED}/start")
    assert hits == [ALLOWED]  # the forbidden target was never contacted


def test_redirect_without_location_is_an_error() -> None:
    with (
        make_client(lambda _: httpx.Response(302)) as client,
        pytest.raises(RedirectNotAllowedError),
    ):
        client.get(f"https://{ALLOWED}/x")


def test_redirect_loop_stops_at_limit() -> None:
    count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(302, headers={"location": f"https://{ALLOWED}/loop"})

    with make_client(handler, max_redirects=3) as client, pytest.raises(RedirectNotAllowedError):
        client.get(f"https://{ALLOWED}/loop")
    assert count == 4  # original + 3 redirects


def test_redirect_does_not_forward_extra_headers_to_other_host() -> None:
    seen: dict[str, str | None] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == ALLOWED:
            return httpx.Response(302, headers={"location": f"https://{OTHER}/x"})
        seen["inm"] = req.headers.get("if-none-match")
        return httpx.Response(200)

    with make_client(handler) as client:
        client.get(f"https://{ALLOWED}/x", extra_headers={"If-None-Match": "abc"})
    assert seen["inm"] is None


# --- size caps -------------------------------------------------------------------------------


def test_declared_content_length_over_cap_is_rejected_without_reading() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 10, headers={"content-length": "999999"})

    # MockTransport may recompute content-length; fall back to the streaming check either way.
    with make_client(handler) as client, pytest.raises(ResponseTooLargeError):
        client.get(f"https://{ALLOWED}/x", max_bytes=100)


def test_streamed_body_over_cap_is_aborted() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    with make_client(handler) as client, pytest.raises(ResponseTooLargeError):
        client.get(f"https://{ALLOWED}/x", max_bytes=1000)


def test_body_exactly_at_cap_is_accepted() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1000)

    with make_client(handler) as client:
        assert len(client.get(f"https://{ALLOWED}/x", max_bytes=1000).body) == 1000


def test_compressed_responses_are_refused_not_decoded() -> None:
    """We request identity encoding; a server that compresses anyway (decompression bomb) is refused."""
    bomb = gzip.compress(b"A" * 5_000_000)
    assert len(bomb) < 10_000

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bomb, headers={"content-encoding": "gzip"})

    with make_client(handler) as client, pytest.raises(NetworkError, match="content-encoding"):
        client.get(f"https://{ALLOWED}/x", max_bytes=100_000)


def test_nested_content_encodings_are_refused_too() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"content-encoding": "gzip, gzip, br"})

    with make_client(handler) as client, pytest.raises(NetworkError):
        client.get(f"https://{ALLOWED}/x")


def test_requests_ask_for_identity_encoding() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["accept-encoding"])
        return httpx.Response(200)

    with make_client(handler) as client:
        client.get(f"https://{ALLOWED}/x")
    assert seen == ["identity"]


@pytest.mark.parametrize("value", ["9" * 5000, "abc", "-1", "1e3"])
def test_malformed_or_absurd_content_length_is_a_network_error(value: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"abc", headers={"content-length": value})

    with make_client(handler) as client, pytest.raises(NetworkError):
        client.get(f"https://{ALLOWED}/x")


class _DripStream(httpx.SyncByteStream):
    def __init__(self, sleep: float, chunks: int) -> None:
        self._sleep, self._chunks = sleep, chunks

    def __iter__(self):  # type: ignore[no-untyped-def]
        import time

        for _ in range(self._chunks):
            time.sleep(self._sleep)
            yield b"x"


def test_total_deadline_is_enforced_while_the_body_trickles_in() -> None:
    import time

    class Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_DripStream(0.1, 100))

    policy = NetworkPolicy(allowed_hosts=frozenset({ALLOWED}), total_timeout=0.35)
    started = time.monotonic()
    with (
        SafeHttpClient(policy, transport=Transport()) as client,
        pytest.raises(NetworkTimeoutError),
    ):
        client.get(f"https://{ALLOWED}/x")
    assert time.monotonic() - started < 1.5  # not the 10 s the server wanted


def test_errors_do_not_carry_the_url_in_their_exception_chain() -> None:
    import traceback

    secret = "800123456"

    def timeout(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out fetching {req.url}")

    def connect(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"boom for {req.url}")

    for handler in (timeout, connect):
        with make_client(handler) as client:
            try:
                client.get(f"https://{ALLOWED}/api/uid/{secret}?k=1")
            except NetworkError as exc:
                text = "".join(traceback.format_exception(exc))
                assert secret not in text, text
                assert exc.__cause__ is None and exc.__context__ is None
            else:  # pragma: no cover
                pytest.fail("expected a NetworkError")


def test_url_logging_stays_off_even_after_the_app_reconfigures_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.INFO)  # what a later logging setup might do
    with make_client(ok) as client:  # constructing a client re-asserts the guard
        client.get(f"https://{ALLOWED}/api/uid/800123456?k=SECRET")
    assert "800123456" not in caplog.text and "SECRET" not in caplog.text


def test_per_call_cap_cannot_exceed_hard_ceiling() -> None:
    with make_client(ok, default_max_bytes=500, hard_max_bytes=1000) as client:
        with pytest.raises(PolicyViolationError):
            client.get(f"https://{ALLOWED}/x", max_bytes=5000)
        with pytest.raises(PolicyViolationError):
            client.get(f"https://{ALLOWED}/x", max_bytes=0)


def test_inconsistent_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="default_max_bytes"):
        NetworkPolicy(allowed_hosts=frozenset(), default_max_bytes=2000, hard_max_bytes=1000)


def test_default_cap_applies_when_none_given() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2000)

    with (
        make_client(handler, default_max_bytes=1000) as client,
        pytest.raises(ResponseTooLargeError),
    ):
        client.get(f"https://{ALLOWED}/x")


# --- failures --------------------------------------------------------------------------------


def test_timeouts_are_mapped() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with make_client(handler) as client, pytest.raises(NetworkTimeoutError):
        client.get(f"https://{ALLOWED}/x")


def test_transport_errors_are_mapped_and_do_not_leak_the_url() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom for https://api.allowed.test/api/uid/800123456")

    with make_client(handler) as client, pytest.raises(NetworkError) as exc:
        client.get(f"https://{ALLOWED}/api/uid/800123456")
    assert "800123456" not in str(exc.value)


def test_policy_errors_are_network_errors() -> None:
    assert issubclass(PolicyViolationError, NetworkError)
    assert issubclass(HostNotAllowedError, PolicyViolationError)
    assert issubclass(RedirectNotAllowedError, PolicyViolationError)
    assert issubclass(ResponseTooLargeError, NetworkError)


# -- red-team round 2 (URL parsing lens) -------------------------------------------------------------


@pytest.mark.parametrize(
    "host", ["127.1", "127.0.1", "10.1", "0x7f.0.0.1", "0x7f.1", "1.1", "a.123"]
)
def test_numeric_looking_allowlist_entries_are_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="allow"):
        NetworkPolicy(allowed_hosts=frozenset({host}))


def test_policy_takes_an_immutable_copy_of_the_allowlist() -> None:
    hosts = {ALLOWED}
    policy = NetworkPolicy(allowed_hosts=hosts)  # type: ignore[arg-type]
    hosts.add("evil.test")
    with (
        SafeHttpClient(policy, transport=StreamingTransport(ok)) as client,
        pytest.raises(HostNotAllowedError),
    ):
        client.get("https://evil.test/x")


def test_string_allowlist_is_rejected() -> None:
    with pytest.raises(ValueError, match="allow"):
        NetworkPolicy(allowed_hosts=ALLOWED)  # type: ignore[arg-type]


def test_empty_port_marker_is_rejected() -> None:
    with make_client(ok) as client, pytest.raises(PolicyViolationError):
        client.get(f"https://{ALLOWED}:/x")


def test_unparseable_url_errors_do_not_chain_the_authority_text() -> None:
    import traceback

    for url in (
        f"https://user800123456:pw@{ALLOWED}＃/p",
        f"https://{ALLOWED}:800123456x/p",
    ):
        with make_client(ok) as client:
            try:
                client.get(url)
            except PolicyViolationError as exc:
                text = "".join(traceback.format_exception(exc))
                assert "800123456" not in text, text
                assert exc.__cause__ is None and exc.__context__ is None
            else:  # pragma: no cover
                pytest.fail("expected PolicyViolationError")
