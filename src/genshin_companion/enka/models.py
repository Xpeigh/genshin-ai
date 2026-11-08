"""Imported roster models. Values keep Enka's display units (percent stats like ``14.0``, not
``0.14``); ``enka.verify`` converts when it checks them against the snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ImportedSubstat(_Frozen):
    stat: str
    value: float


class ImportedArtifact(_Frozen):
    item_id: int
    slot: str  # EQUIP_BRACER flower, NECKLACE feather, SHOES sands, RING goblet, DRESS circlet
    rarity: int = Field(ge=1, le=5)
    level: int = Field(ge=0, le=20)  # real level (Enka reports level + 1)
    set_id: int | None
    set_name_hash: str | None
    main_stat: str
    main_value: float
    substats: list[ImportedSubstat]
    roll_affix_ids: list[str]  # one id per roll (initial substats + upgrades), in order


class ImportedWeapon(_Frozen):
    item_id: int
    level: int
    refinement: int = Field(ge=1, le=5)
    rarity: int | None
    name_hash: str | None
    stats: dict[str, float]


class ImportedCharacter(_Frozen):
    avatar_id: int
    level: int
    constellation: int = Field(ge=0, le=6)
    # Enka's documented "Character Skill Set ID". Recorded as sent; not yet used to pick a Traveler
    # variant, because how it relates to the per-element ids in the store is not documented.
    skill_depot_id: int | None = Field(default=None, ge=0, le=10**9)
    weapon: ImportedWeapon | None
    artifacts: list[ImportedArtifact]


class Roster(_Frozen):
    uid: str = Field(pattern=r"^[1-9][0-9]{8,9}$")
    region: str | None
    nickname: str | None
    player_level: int | None
    ttl: int = Field(ge=0)
    fetched_at: datetime
    source: Literal["enka", "file"] = "enka"
    showcase_open: bool
    showcase_size: int  # characters the player lists on their showcase
    characters: list[ImportedCharacter]
    notes: list[str]
