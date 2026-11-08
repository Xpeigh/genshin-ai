from __future__ import annotations

import json
from pathlib import Path

import pytest

from genshin_companion.data.models import Snapshot
from genshin_companion.data.store import SnapshotStore, StoreError
from genshin_companion.paths import ensure_layout
from helpers import snapshot


@pytest.fixture
def store(tmp_path: Path) -> SnapshotStore:
    return SnapshotStore(ensure_layout(tmp_path / "home"))


def bump(snap: Snapshot, **changes: object) -> Snapshot:
    return snap.model_copy(update=changes)


RAW = {"affixes": b"{}"}


def test_empty_store_has_no_current(store: SnapshotStore) -> None:
    assert store.current() is None
    assert store.history() == []


def test_stage_then_promote_makes_it_current(store: SnapshotStore) -> None:
    staged = store.stage(snapshot(), RAW)
    assert staged.parent == store.layout.quarantine  # never written straight to snapshots
    assert store.current() is None
    sid = store.promote(staged)
    assert store.current() == snapshot()
    assert store.history() == [sid]
    assert not staged.exists()  # moved, not copied
    assert (store.layout.snapshots / sid / "raw" / "affixes.json").read_bytes() == b"{}"


def test_second_promote_keeps_previous_for_rollback(store: SnapshotStore) -> None:
    first = store.promote(store.stage(snapshot(), RAW))
    second_snap = bump(snapshot(), game_version="7.3")
    second = store.promote(store.stage(second_snap, RAW))
    assert store.current() == second_snap
    assert store.history() == [first, second]
    assert store.rollback() == first
    assert store.current() == snapshot()
    assert store.history() == [first, second]  # history is kept; pointer moved back


def test_rollback_without_previous_fails(store: SnapshotStore) -> None:
    store.promote(store.stage(snapshot(), RAW))
    with pytest.raises(StoreError, match="no earlier"):
        store.rollback()


def test_corrupted_snapshot_is_detected(store: SnapshotStore) -> None:
    sid = store.promote(store.stage(snapshot(), RAW))
    path = store.layout.snapshots / sid / "snapshot.json"
    path.write_text(path.read_text(encoding="utf-8").replace("7.2", "9.9"), encoding="utf-8")
    with pytest.raises(StoreError, match="integrity"):
        store.current()


def test_tampered_pointer_with_path_traversal_is_rejected(store: SnapshotStore) -> None:
    store.promote(store.stage(snapshot(), RAW))
    pointer = store.layout.snapshots / "current.json"
    pointer.write_text(json.dumps({"current": "../../etc", "history": ["../../etc"]}))
    with pytest.raises(StoreError):
        store.current()


def test_pruning_keeps_current_and_previous(store: SnapshotStore) -> None:
    ids = []
    for i in range(7):
        ids.append(store.promote(store.stage(bump(snapshot(), game_version=f"7.{i}"), RAW)))
    remaining = {p.name for p in store.layout.snapshots.iterdir() if p.is_dir()}
    assert ids[-1] in remaining and ids[-2] in remaining
    assert len(remaining) <= 5


def test_promote_refuses_directories_outside_quarantine(
    store: SnapshotStore, tmp_path: Path
) -> None:
    rogue = tmp_path / "rogue"
    rogue.mkdir()
    with pytest.raises(StoreError, match="quarantine"):
        store.promote(rogue)


def test_rolled_back_pointer_survives_new_promote(store: SnapshotStore) -> None:
    a = store.promote(store.stage(snapshot(), RAW))
    store.promote(store.stage(bump(snapshot(), game_version="7.3"), RAW))
    store.rollback()
    c = store.promote(store.stage(bump(snapshot(), game_version="7.4"), RAW))
    assert store.history()[-1] == c
    assert a in store.history()
