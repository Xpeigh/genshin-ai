"""Normalised game-data models: what the rest of the app (scoring, builds, chat) sees.

Everything here is produced from *validated* downloads, never from memory. Models are frozen and
reject unknown fields so a silent schema change in our own snapshot files cannot go unnoticed.

Units: stat values are stored exactly as the upstream source gives them. Percentages are
fractions (``0.0583`` means 5.83%); flat stats are plain numbers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 2  # 2: SubstatTier.affix_id (lets imported artifacts be decomposed into rolls)

# verified    = hand-checked against the game by Ben (golden fixtures); never set automatically
# curated     = two independent sources agree, or a human approved the entry
# provisional = single source, sources disagree, or data version is unknown/old
Confidence = Literal["verified", "curated", "provisional"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SubstatTier(_Frozen):
    """One possible value of a single substat roll at a given rarity (position 1 = lowest)."""

    affix_id: str = Field(pattern=r"^[0-9]{6}$")  # the id Enka lists in appendPropIdList
    rarity: int = Field(ge=1, le=5)
    stat: str = Field(pattern=r"^FIGHT_PROP_[A-Z_]+$")
    position: int = Field(ge=1, le=4)
    value: float = Field(gt=0)


class MainStatValue(_Frozen):
    """Main-stat value of a piece of ``rarity`` at ``level`` (0 = unleveled)."""

    rarity: int = Field(ge=1, le=5)
    level: int = Field(ge=0, le=20)
    stat: str = Field(pattern=r"^FIGHT_PROP_[A-Z_]+$")
    value: float = Field(gt=0)


class Character(_Frozen):
    id: str = Field(pattern=r"^[0-9]+(-[0-9]+)?$")
    name: str | None
    element: str
    weapon_type: str | None  # None for entries upstream does not assign a weapon (Traveler)
    quality: str
    base_props: dict[str, float]  # upstream numeric prop ids as strings, see Snapshot.prop_names


class Weapon(_Frozen):
    id: str = Field(pattern=r"^[0-9]+$")
    name: str | None
    rarity: int = Field(ge=1, le=5)
    weapon_type: int
    base_props: dict[str, float]


class ArtifactSet(_Frozen):
    id: str = Field(pattern=r"^[0-9]+$")
    name: str | None
    add_props: dict[str, float]  # upstream fields, kept verbatim; bonus text is not in this source


class ArtifactPiece(_Frozen):
    id: str = Field(pattern=r"^[0-9]+$")
    rarity: int = Field(ge=1, le=5)
    equip_type: int
    set_id: str = Field(pattern=r"^[0-9]+$")


class SourceRecord(_Frozen):
    """Where a downloaded file came from. ``ref`` is a commit SHA, or a branch name if unpinned."""

    source: str
    url: str
    ref: str
    pinned: bool
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    fetched_at: datetime


class Snapshot(_Frozen):
    schema_version: int = SCHEMA_VERSION
    game_version: str  # e.g. "7.2"; "unknown" when no source could establish it
    fetched_at: datetime
    sources: list[SourceRecord]
    # per-dataset confidence: substat_tiers, main_stats, characters, weapons, artifact_sets
    confidence: dict[str, Confidence]
    notes: list[str]  # human-readable disagreements and caveats found while building
    prop_names: dict[str, str]  # upstream numeric prop id -> FIGHT_PROP_*, derived from data
    substat_tiers: list[SubstatTier]
    main_stats: list[MainStatValue]
    characters: list[Character]
    weapons: list[Weapon]
    artifact_sets: list[ArtifactSet]
    artifacts: list[ArtifactPiece]

    def tiers_for(self, rarity: int, stat: str) -> list[SubstatTier]:
        return sorted(
            (t for t in self.substat_tiers if t.rarity == rarity and t.stat == stat),
            key=lambda t: t.position,
        )
