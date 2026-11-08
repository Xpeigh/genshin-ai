"""Smoke test against REAL downloaded data (parsing-assumption guard).

Skipped unless GENSHIN_REAL_DATA_DIR points at a folder holding the raw files: affixes.json,
affixes_legacy.json, relic_levels.json, avatars.json, weapons.json, relics.json, locs.json,
reliquaryCurve.json, changelog.json. They are never committed (upstream has no licence); `sync`
keeps a copy under snapshots/<id>/raw/ that can be used here.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from genshin_companion.data.normalize import (
    AMBER_FILES,
    ENKA_FILES,
    build_snapshot,
    parse_amber,
    parse_enka,
)

_DIR = os.environ.get("GENSHIN_REAL_DATA_DIR")
pytestmark = pytest.mark.skipif(not _DIR, reason="set GENSHIN_REAL_DATA_DIR to run")


def _read(names: tuple[str, ...]) -> dict[str, bytes]:
    assert _DIR
    return {n: (Path(_DIR) / f"{n}.json").read_bytes() for n in names}


def test_real_data_builds_and_cross_checks() -> None:
    snap = build_snapshot(
        parse_enka(_read(ENKA_FILES)),
        parse_amber(_read(AMBER_FILES)),
        sources=[],
        fetched_at=datetime.now(UTC),
    )
    print("game_version", snap.game_version, "confidence", snap.confidence)
    for n in snap.notes[:30]:
        print("note:", n)
    assert snap.game_version != "unknown"
    assert snap.confidence["substat_tiers"] == "curated", snap.notes
    assert len(snap.characters) > 50 and len(snap.weapons) > 100 and len(snap.artifact_sets) > 30
    # every rarity 3..5 substat has four tiers, 1..2 fewer; all ten substats present at 5 stars
    five = {t.stat for t in snap.substat_tiers if t.rarity == 5}
    assert len(five) == 10
    for stat in five:
        assert [t.position for t in snap.tiers_for(5, stat)] == [1, 2, 3, 4]
