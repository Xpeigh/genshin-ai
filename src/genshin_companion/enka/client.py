"""Fetch a showcase from Enka, honouring its rules (docs read 2026-11-08):

* one request per user-supplied UID, never any enumeration;
* a descriptive User-Agent (set by ``net``);
* cache every response for its ``ttl`` seconds on disk and do not call again before it runs out;
* handle 400/404/424/429/5xx explicitly. A private or empty showcase is a 200 without characters.

The UID is part of the request URL: this is the one unavoidable exception to "nothing about the user
leaves the machine" (README). Error messages never contain the UID.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from genshin_companion.enka.mapping import EnkaFormatError, parse_showcase
from genshin_companion.enka.models import Roster
from genshin_companion.net import SafeHttpClient

_UID = re.compile(r"^[1-9][0-9]{8,9}$")
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class EnkaError(Exception):
    """Base class; messages never include the UID."""


class InvalidUidError(EnkaError):
    pass


class PlayerNotFoundError(EnkaError):
    pass


class EnkaMaintenanceError(EnkaError):
    pass


class EnkaServerError(EnkaError):
    pass


class EnkaRateLimitedError(EnkaError):
    def __init__(self, retry_after: int | None) -> None:
        super().__init__("rate limited by Enka or the game server; slow down")
        self.retry_after = retry_after


@dataclass(slots=True)
class FetchResult:
    roster: Roster
    from_cache: bool
    seconds_until_refresh: int  # 0 when a new request is allowed right now


def _cache_path(cache_dir: Path, uid: str) -> Path:
    return cache_dir / "enka" / f"{uid}.json"


def _read_cache(path: Path, uid: str, now: datetime) -> FetchResult | None:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(saved["fetched_at"])
        body = json.dumps(saved["response"]).encode()
        roster = parse_showcase(body, fetched_at=fetched_at)
    except (OSError, ValueError, KeyError, TypeError, EnkaFormatError):
        return None
    if roster.uid != uid or fetched_at > now:
        return None
    remaining = int((fetched_at + timedelta(seconds=roster.ttl) - now).total_seconds())
    if remaining <= 0:
        return None
    return FetchResult(roster, True, remaining)


def _write_cache(path: Path, response: object, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"fetched_at": now.isoformat(), "response": response}), encoding="utf-8"
    )
    os.replace(tmp, path)


def fetch_roster(uid: str, client: SafeHttpClient, cache_dir: Path, now: datetime) -> FetchResult:
    if not isinstance(uid, str) or not _UID.match(uid):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise InvalidUidError("a UID is 9-10 digits and does not start with 0")
    path = _cache_path(cache_dir, uid)
    cached = _read_cache(path, uid, now)
    if cached is not None:
        return cached

    resp = client.get(f"https://enka.network/api/uid/{uid}/", max_bytes=MAX_RESPONSE_BYTES)
    status = resp.status
    if status == 400:
        raise InvalidUidError("Enka says the UID format is wrong")
    if status == 404:
        raise PlayerNotFoundError("the game server says this player does not exist")
    if status == 424:
        raise EnkaMaintenanceError("game maintenance, or broken after an update; try later")
    if status == 429:
        retry = resp.headers.get("retry-after", "")
        raise EnkaRateLimitedError(int(retry) if retry.isdigit() and len(retry) < 9 else None)
    if status >= 500:
        raise EnkaServerError(f"Enka server error (HTTP {status})")
    if status != 200:
        raise EnkaError(f"unexpected HTTP status {status}")

    try:
        roster = parse_showcase(resp.body, fetched_at=now)
    except EnkaFormatError as exc:
        raise EnkaError(f"unreadable response: {exc}") from None
    if roster.uid != uid:
        raise EnkaError("Enka answered for a different UID; ignoring it")
    _write_cache(path, json.loads(resp.body), now)
    return FetchResult(roster, False, roster.ttl)
