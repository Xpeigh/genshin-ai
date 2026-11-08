from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from genshin_companion.config import default_network_policy
from genshin_companion.enka.client import (
    EnkaMaintenanceError,
    EnkaRateLimitedError,
    EnkaServerError,
    InvalidUidError,
    PlayerNotFoundError,
    fetch_roster,
)
from genshin_companion.net import SafeHttpClient
from helpers import StreamingTransport
from test_enka_mapping import showcase

UID = "800123456"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


class Enka:
    def __init__(self, status: int = 200, body: bytes | None = None, headers: dict | None = None):
        self.requests: list[httpx.Request] = []
        self.status, self.body, self.headers = status, body or showcase(), headers or {}

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return httpx.Response(self.status, content=self.body, headers=self.headers)

    def client(self) -> SafeHttpClient:
        return SafeHttpClient(default_network_policy(), transport=StreamingTransport(self.handler))


def test_fetch_requests_the_documented_endpoint_and_caches(tmp_path: Path) -> None:
    server = Enka()
    with server.client() as client:
        result = fetch_roster(UID, client, tmp_path, NOW)
    assert not result.from_cache and result.roster.uid == UID
    assert [str(r.url) for r in server.requests] == [f"https://enka.network/api/uid/{UID}/"]
    assert server.requests[0].method == "GET"
    assert (tmp_path / "enka" / f"{UID}.json").exists()


def test_cache_is_used_until_ttl_expires_and_never_hits_the_network(tmp_path: Path) -> None:
    server = Enka()  # showcase() has ttl 60
    with server.client() as client:
        fetch_roster(UID, client, tmp_path, NOW)
        again = fetch_roster(UID, client, tmp_path, NOW + timedelta(seconds=59))
        assert again.from_cache and again.seconds_until_refresh == 1
        assert len(server.requests) == 1
        fetch_roster(UID, client, tmp_path, NOW + timedelta(seconds=61))
        assert len(server.requests) == 2


def test_cache_dated_in_the_future_is_not_trusted(tmp_path: Path) -> None:
    server = Enka()
    with server.client() as client:
        fetch_roster(UID, client, tmp_path, NOW + timedelta(days=1))
        fetch_roster(UID, client, tmp_path, NOW)
    assert len(server.requests) == 2


def test_corrupt_cache_is_ignored(tmp_path: Path) -> None:
    server = Enka()
    (tmp_path / "enka").mkdir()
    (tmp_path / "enka" / f"{UID}.json").write_text("{not json")
    with server.client() as client:
        assert not fetch_roster(UID, client, tmp_path, NOW).from_cache


@pytest.mark.parametrize(
    "uid", ["", "123", "abc123456", "0123456789", "../../etc", "1" * 11, "800123456/x"]
)
def test_invalid_uid_is_refused_before_any_request(uid: str, tmp_path: Path) -> None:
    server = Enka()
    with server.client() as client, pytest.raises(InvalidUidError):
        fetch_roster(uid, client, tmp_path, NOW)
    assert server.requests == []


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, InvalidUidError),
        (404, PlayerNotFoundError),
        (424, EnkaMaintenanceError),
        (429, EnkaRateLimitedError),
        (500, EnkaServerError),
        (503, EnkaServerError),
    ],
)
def test_documented_status_codes_map_to_typed_errors(
    status: int, error: type, tmp_path: Path
) -> None:
    server = Enka(status=status, body=b"{}")
    with server.client() as client, pytest.raises(error) as exc:
        fetch_roster(UID, client, tmp_path, NOW)
    assert UID not in str(exc.value)
    assert not (tmp_path / "enka").exists() or not list((tmp_path / "enka").iterdir())


def test_rate_limit_reports_retry_after(tmp_path: Path) -> None:
    server = Enka(status=429, body=b"{}", headers={"retry-after": "30"})
    with server.client() as client, pytest.raises(EnkaRateLimitedError) as exc:
        fetch_roster(UID, client, tmp_path, NOW)
    assert exc.value.retry_after == 30


def test_failed_fetch_does_not_poison_the_cache(tmp_path: Path) -> None:
    server = Enka(body=b"<html>gateway</html>")
    with server.client() as client, pytest.raises(Exception):  # noqa: B017
        fetch_roster(UID, client, tmp_path, NOW)
    assert not (tmp_path / "enka" / f"{UID}.json").exists()


def test_payload_for_a_different_uid_is_rejected(tmp_path: Path) -> None:
    server = Enka(body=showcase(uid="900123456"))
    with server.client() as client, pytest.raises(Exception, match="different"):
        fetch_roster(UID, client, tmp_path, NOW)


def test_cache_file_contents_are_just_the_response_and_a_timestamp(tmp_path: Path) -> None:
    with Enka().client() as client:
        fetch_roster(UID, client, tmp_path, NOW)
    saved = json.loads((tmp_path / "enka" / f"{UID}.json").read_text())
    assert set(saved) == {"fetched_at", "response"}
