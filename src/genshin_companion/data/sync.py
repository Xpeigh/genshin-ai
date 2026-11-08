"""`sync`: download -> normalise -> cross-check -> validate -> quarantine -> promote (or hold).

Nothing downloaded is trusted until it has passed through ``normalize`` (strict parsing) and
``validate`` (sanity + diff-size gate). A rejected or held candidate stays in quarantine and the
last-known-good snapshot remains current.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from genshin_companion.data import sources
from genshin_companion.data.changelog import diff, render
from genshin_companion.data.models import SourceRecord
from genshin_companion.data.normalize import (
    NormalizeError,
    build_snapshot,
    parse_amber,
    parse_enka,
)
from genshin_companion.data.store import SnapshotStore, StoreError
from genshin_companion.data.validate import ValidationReport, validate
from genshin_companion.net import NetworkError, SafeHttpClient
from genshin_companion.paths import DataLayout

Status = Literal["promoted", "unchanged", "held", "rejected", "failed"]


@dataclass(slots=True)
class SyncResult:
    status: Status
    message: str
    snapshot_id: str | None = None
    staged: Path | None = None
    report: ValidationReport | None = None


class _FetchError(Exception):
    pass


def _fetch(
    client: SafeHttpClient, files: list[sources.SourceFile], ref: str, now: datetime
) -> tuple[dict[str, bytes], list[SourceRecord]]:
    out: dict[str, bytes] = {}
    records: list[SourceRecord] = []
    for f in files:
        try:
            resp = client.get(f.url, max_bytes=f.max_bytes)
        except NetworkError as exc:
            raise _FetchError(f"{f.source}/{f.name}: {exc}") from exc
        if resp.status != 200:
            raise _FetchError(f"{f.source}/{f.name}: HTTP {resp.status}")
        out[f.name] = resp.body
        records.append(
            SourceRecord(
                source=f.source,
                url=f.url,
                ref=ref if f.source == "enka" else "latest",
                pinned=sources.is_pinned(ref) if f.source == "enka" else False,
                sha256=hashlib.sha256(resp.body).hexdigest(),
                bytes=len(resp.body),
                fetched_at=now,
            )
        )
    return out, records


def run_sync(
    layout: DataLayout,
    client: SafeHttpClient,
    *,
    now: datetime,
    ref: str = sources.ENKA_PINNED_REF,
    allow_single_source: bool = False,
    accept_held: bool = False,
) -> SyncResult:
    store = SnapshotStore(layout)
    try:
        enka_raw, records = _fetch(client, sources.enka_files(ref), ref, now)
    except _FetchError as exc:
        return SyncResult("failed", f"download failed: {exc}")
    amber_raw: dict[str, bytes] = {}
    try:
        amber_raw, amber_records = _fetch(client, sources.amber_files(), ref, now)
        records += amber_records
    except _FetchError as exc:
        if not allow_single_source:
            return SyncResult(
                "failed",
                f"cross-check source unavailable ({exc}); re-run with --allow-single-source "
                "to accept provisional data",
            )

    try:
        snap = build_snapshot(
            parse_enka(enka_raw),
            parse_amber(amber_raw) if amber_raw else None,
            sources=records,
            fetched_at=now,
        )
        previous = store.current()
    except (NormalizeError, StoreError) as exc:
        return SyncResult("failed", f"data rejected before staging: {exc}")

    if previous is not None and previous.model_dump(
        exclude={"fetched_at", "sources"}
    ) == snap.model_dump(exclude={"fetched_at", "sources"}):
        return SyncResult("unchanged", "downloaded data is identical to the current snapshot")

    report = validate(snap, previous)
    staged = store.stage(snap, {**enka_raw, **amber_raw})
    if report.status == "rejected":
        return SyncResult(
            "rejected",
            "snapshot failed validation: " + "; ".join(report.errors),
            None,
            staged,
            report,
        )
    if report.status == "held" and not accept_held:
        return SyncResult(
            "held",
            "snapshot held for review: "
            + "; ".join(report.review_reasons)
            + " (re-run with --accept-held after reading the changelog)",
            None,
            staged,
            report,
        )
    snapshot_id = store.promote(staged)
    if previous is not None:
        (layout.snapshots / snapshot_id / "CHANGELOG.md").write_text(
            render(diff(previous, snap)), encoding="utf-8"
        )
    return SyncResult(
        "promoted",
        f"snapshot {snapshot_id} is now current (game {snap.game_version})",
        snapshot_id,
        None,
        report,
    )
