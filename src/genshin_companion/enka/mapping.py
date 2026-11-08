"""Enka payload -> internal models. The ONLY place that knows Enka's response layout, so an API
change touches this file alone (SPEC.md, "Enka import")."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from genshin_companion.enka.models import (
    ImportedArtifact,
    ImportedCharacter,
    ImportedSubstat,
    ImportedWeapon,
    Roster,
)

MAX_AVATARS = 50
MAX_EQUIP = 20
MAX_ROLLS = 30


class EnkaFormatError(Exception):
    """The payload is not a showcase response we understand."""


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Stat(_Raw):
    statValue: float


class _MainStat(_Stat):
    mainPropId: str


class _SubStat(_Stat):
    appendPropId: str


class _RawReliquary(_Raw):
    level: int
    appendPropIdList: list[int] = []


class _RawWeapon(_Raw):
    level: int
    affixMap: dict[str, int] = {}


class _RawFlat(_Raw):
    nameTextMapHash: int | str | None = None
    rankLevel: int | None = None
    equipType: str | None = None
    setId: int | None = None
    setNameTextMapHash: int | str | None = None
    reliquaryMainstat: _MainStat | None = None
    reliquarySubstats: list[_SubStat] = []
    weaponStats: list[_SubStat] = []


class _RawEquip(_Raw):
    itemId: int
    reliquary: _RawReliquary | None = None
    weapon: _RawWeapon | None = None
    flat: _RawFlat


def _hash(value: int | str | None) -> str | None:
    return None if value is None else str(value)


def _artifact(e: _RawEquip) -> ImportedArtifact:
    rel, flat = e.reliquary, e.flat
    if rel is None or flat.reliquaryMainstat is None or flat.rankLevel is None:
        raise ValueError("incomplete artifact")
    if len(rel.appendPropIdList) > MAX_ROLLS:
        raise ValueError("too many rolls")
    return ImportedArtifact(
        item_id=e.itemId,
        slot=flat.equipType or "UNKNOWN",
        rarity=flat.rankLevel,
        level=rel.level - 1,
        set_id=flat.setId,
        set_name_hash=_hash(flat.setNameTextMapHash),
        main_stat=flat.reliquaryMainstat.mainPropId,
        main_value=flat.reliquaryMainstat.statValue,
        substats=[
            ImportedSubstat(stat=s.appendPropId, value=s.statValue) for s in flat.reliquarySubstats
        ],
        roll_affix_ids=[str(i) for i in rel.appendPropIdList],
    )


def _weapon(e: _RawEquip) -> ImportedWeapon:
    if e.weapon is None:
        raise ValueError("incomplete weapon")
    refinement = max(e.weapon.affixMap.values(), default=0) + 1  # Enka reports 0-4
    return ImportedWeapon(
        item_id=e.itemId,
        level=e.weapon.level,
        refinement=refinement,
        rarity=e.flat.rankLevel,
        name_hash=_hash(e.flat.nameTextMapHash),
        stats={s.appendPropId: s.statValue for s in e.flat.weaponStats},
    )


def _character(raw: dict[str, Any], notes: list[str]) -> ImportedCharacter:
    avatar_id = int(raw["avatarId"])
    level = int(raw["propMap"]["4001"]["val"])
    equip_list = raw.get("equipList", [])
    if len(equip_list) > MAX_EQUIP:
        raise EnkaFormatError("too many equipment entries")
    weapon: ImportedWeapon | None = None
    artifacts: list[ImportedArtifact] = []
    for item in equip_list:
        try:
            equip = _RawEquip.model_validate(item)
            if equip.reliquary is not None:
                artifacts.append(_artifact(equip))
            elif equip.weapon is not None:
                weapon = _weapon(equip)
            else:
                raise ValueError("neither artifact nor weapon")
        except (ValidationError, ValueError):
            notes.append(f"equipment skipped for avatar {avatar_id}: unreadable entry")
    return ImportedCharacter(
        avatar_id=avatar_id,
        level=level,
        constellation=len(raw.get("talentIdList", [])),
        weapon=weapon,
        artifacts=artifacts,
    )


def parse_showcase(
    body: bytes, *, fetched_at: datetime, source: Literal["enka", "file"] = "enka"
) -> Roster:
    try:
        data = json.loads(body)
    except (ValueError, RecursionError) as exc:
        raise EnkaFormatError("response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise EnkaFormatError("response is not a JSON object")
    uid = data.get("uid")
    ttl = data.get("ttl")
    info = data.get("playerInfo")
    if not isinstance(uid, str) or not isinstance(info, dict) or not isinstance(ttl, int):
        raise EnkaFormatError("response lacks uid / playerInfo / ttl")
    avatars = data.get("avatarInfoList")
    shown = info.get("showAvatarInfoList") or []
    if avatars is not None and (not isinstance(avatars, list) or len(avatars) > MAX_AVATARS):
        raise EnkaFormatError("too many entries or malformed avatarInfoList")
    if not isinstance(shown, list) or len(shown) > MAX_AVATARS:
        raise EnkaFormatError("too many entries or malformed showAvatarInfoList")

    notes: list[str] = []
    characters: list[ImportedCharacter] = []
    for raw in avatars or []:
        try:
            characters.append(_character(raw, notes))
        except (KeyError, TypeError, ValueError, ValidationError):
            notes.append("a character entry was skipped: unreadable")
    if not avatars:
        notes.append(
            "Showcase closed or empty: Enka returned no characters. In game, add characters to "
            "the Character Showcase and enable showing their details."
        )
    else:
        notes.append(
            f"Enka only exposes the characters on the player's showcase ({len(characters)} "
            "returned); the rest of the roster is invisible to this import (showcase subset)."
        )
    try:
        return Roster(
            uid=uid,
            region=data["region"] if isinstance(data.get("region"), str) else None,
            nickname=info["nickname"] if isinstance(info.get("nickname"), str) else None,
            player_level=info["level"] if isinstance(info.get("level"), int) else None,
            ttl=ttl,
            fetched_at=fetched_at,
            source=source,
            showcase_open=bool(avatars),
            showcase_size=len(shown),
            characters=characters,
            notes=notes,
        )
    except ValidationError as exc:
        raise EnkaFormatError("response failed validation") from exc
