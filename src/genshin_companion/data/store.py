"""On-disk snapshot store: quarantine -> promote, last-known-good history, rollback, integrity.

Layout (under the app home, see ``paths.py``)::

    quarantine/<id>/            freshly built, NOT yet trusted
        snapshot.json, snapshot.sha256, raw/<file>.json
    snapshots/<id>/             promoted snapshots (same files)
    snapshots/current.json      {"current": id, "history": [oldest ... newest]}

Snapshot ids are ``YYYYMMDDTHHMMSSZ-<8 hex of content hash>``; anything else read from disk is
refused, so a tampered pointer cannot escape the snapshot directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from genshin_companion.data.models import Snapshot
from genshin_companion.paths import DataLayout

KEEP: Final = 5
_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
_RAW_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
POINTER = "current.json"


class StoreError(Exception):
    """The snapshot store is missing, corrupt or was asked to do something unsafe."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SnapshotStore:
    def __init__(self, layout: DataLayout) -> None:
        self.layout = layout

    # -- pointer ----------------------------------------------------------------------------

    def _read_pointer(self) -> tuple[str | None, list[str]]:
        path = self.layout.snapshots / POINTER
        if not path.exists():
            return None, []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            current, history = data["current"], data["history"]
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise StoreError("pointer file is unreadable") from exc
        if (
            not isinstance(history, list)
            or not all(isinstance(h, str) and _ID.match(h) for h in history)
            or not isinstance(current, str)
            or not _ID.match(current)
            or current not in history
        ):
            raise StoreError("pointer file contains an invalid snapshot id")
        return current, history

    def _write_pointer(self, current: str, history: list[str]) -> None:
        path = self.layout.snapshots / POINTER
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"current": current, "history": history}), encoding="utf-8")
        os.replace(tmp, path)

    # -- reading ----------------------------------------------------------------------------

    def history(self) -> list[str]:
        return self._read_pointer()[1]

    def current_id(self) -> str | None:
        return self._read_pointer()[0]

    def current(self) -> Snapshot | None:
        current, _ = self._read_pointer()
        return None if current is None else self.load(current)

    def load(self, snapshot_id: str) -> Snapshot:
        if not _ID.match(snapshot_id):
            raise StoreError("invalid snapshot id")
        base = self.layout.snapshots / snapshot_id
        return self._load_dir(base)

    @staticmethod
    def _load_dir(base: Path) -> Snapshot:
        try:
            body = (base / "snapshot.json").read_bytes()
            expected = (base / "snapshot.sha256").read_text(encoding="ascii").strip()
        except OSError as exc:
            raise StoreError(f"snapshot files missing in {base.name}") from exc
        if _sha(body) != expected:
            raise StoreError(f"integrity check failed for snapshot {base.name}")
        try:
            return Snapshot.model_validate_json(body)
        except ValidationError as exc:
            raise StoreError(f"snapshot {base.name} no longer matches the schema") from exc

    # -- writing ----------------------------------------------------------------------------

    def stage(self, snapshot: Snapshot, raw_files: dict[str, bytes]) -> Path:
        """Write a candidate into quarantine. Nothing here is trusted yet."""
        body = snapshot.model_dump_json(indent=2).encode("utf-8")
        digest = _sha(body)
        stamp = snapshot.fetched_at.strftime("%Y%m%dT%H%M%SZ")
        staged = self.layout.quarantine / f"{stamp}-{digest[:8]}"
        if staged.exists():
            shutil.rmtree(staged)
        (staged / "raw").mkdir(parents=True)
        (staged / "snapshot.json").write_bytes(body)
        (staged / "snapshot.sha256").write_text(digest, encoding="ascii")
        for name, content in raw_files.items():
            if not _RAW_NAME.match(name):
                raise StoreError("invalid raw file name")
            (staged / "raw" / f"{name}.json").write_bytes(content)
        return staged

    def promote(self, staged: Path) -> str:
        resolved = staged.resolve()
        if resolved.parent != self.layout.quarantine.resolve():
            raise StoreError("only directories directly inside quarantine can be promoted")
        snapshot_id = resolved.name
        if not _ID.match(snapshot_id):
            raise StoreError("invalid snapshot id")
        self._load_dir(resolved)  # integrity + schema re-check right before trusting it
        dest = self.layout.snapshots / snapshot_id
        if dest.exists():
            shutil.rmtree(resolved)  # identical content already promoted
        else:
            os.replace(resolved, dest)
        _, history = self._read_pointer()
        history = [h for h in history if h != snapshot_id] + [snapshot_id]
        kept = history[-KEEP:]
        self._write_pointer(snapshot_id, kept)
        for child in self.layout.snapshots.iterdir():
            if child.is_dir() and _ID.match(child.name) and child.name not in kept:
                shutil.rmtree(child)
        return snapshot_id

    def rollback(self) -> str:
        current, history = self._read_pointer()
        if current is None:
            raise StoreError("no snapshot to roll back from")
        index = history.index(current)
        if index == 0:
            raise StoreError("no earlier snapshot is available")
        previous = history[index - 1]
        self._load_dir(self.layout.snapshots / previous)  # never point at a corrupt snapshot
        self._write_pointer(previous, history)
        return previous
