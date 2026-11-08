"""Turn untrusted downloaded files into a validated :class:`Snapshot`. Pure functions, no network.

Primary source: Enka `store/gi/*` (IDs match showcase imports). Cross-check source: Project Amber
`reliquaryCurve` + `changelog`. Agreement of both marks a dataset ``curated``; anything else
(single source, or any disagreement) is ``provisional`` and the disagreement is written to
``Snapshot.notes``.

Parsing assumptions that are NOT stated by the upstream docs (each is verified by the cross-check
and, for real data, by ``tests/test_real_data_smoke.py``):

* Substat affix ids look like ``<rarity digit>01<2-digit PropType><position>`` (e.g. 5-star, prop 2,
  position 1). An id whose digits disagree with its own fields is skipped and noted, never trusted.
* Enka ``relic_levels`` / Amber ``ranked`` level keys are one-based: key ``"1"`` is the +0 piece.
* Numeric prop ids are named only from data (legacy affix join, then main-stat value matching).
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from genshin_companion.data.models import (
    ArtifactPiece,
    ArtifactSet,
    Character,
    Confidence,
    MainStatValue,
    Snapshot,
    SourceRecord,
    SubstatTier,
    Weapon,
)

_M = TypeVar("_M", bound=BaseModel)

MAX_ENTRIES: Final = 200_000
MAX_SKIPPED_ABSOLUTE: Final = 5
MAX_SKIPPED_FRACTION: Final = 0.05
_AFFIX_ID = re.compile(r"^([1-5])01(\d{2})([1-4])$")
_VERSION = re.compile(r"^\d{1,2}\.\d{1,2}$")
_FIGHT_PROP = re.compile(r"^FIGHT_PROP_[A-Z_]+$")

ENKA_FILES: Final = (
    "affixes", "affixes_legacy", "relic_levels", "avatars", "weapons", "relics", "locs",
)  # fmt: skip
AMBER_FILES: Final = ("reliquaryCurve", "changelog")


class NormalizeError(Exception):
    """Downloaded data is unusable. Nothing is promoted."""


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _RawAffix(_Raw):
    PropType: int
    Position: int
    Value: float


class _RawLegacyAffix(_Raw):
    propType: str = Field(pattern=r"^FIGHT_PROP_[A-Z_]+$")


class _RawAvatar(_Raw):
    Element: str
    NameTextMapHash: int
    QualityType: str
    WeaponType: str | None = None  # absent for the Traveler and placeholder entries
    BaseProps: dict[str, float]


class _RawWeapon(_Raw):
    Rarity: int
    WeaponType: int
    NameTextMapHash: int
    BaseProps: dict[str, float]


class _RawItem(_Raw):
    Rarity: int
    EquipType: int
    SetId: int


class _RawSet(_Raw):
    Name: str
    AddProps: dict[str, float] = {}


@dataclass(slots=True)
class EnkaRaw:
    affixes: dict[str, _RawAffix]
    legacy_prop_types: dict[str, str]
    relic_levels: dict[str, dict[str, dict[str, float]]]
    avatars: dict[str, _RawAvatar]
    weapons: dict[str, _RawWeapon]
    items: dict[str, _RawItem]
    sets: dict[str, _RawSet]
    locs_en: dict[str, str]
    skipped: list[str] = field(default_factory=list)
    total_entities: int = 0


@dataclass(slots=True)
class AmberRaw:
    affix: dict[str, dict[str, list[float]]]  # rarity -> stat -> ascending roll values
    ranked: dict[str, dict[str, dict[str, float]]]  # rarity -> level key -> stat -> value
    versions: dict[int, str]  # numeric changelog key -> declared version string


# -- JSON helpers ---------------------------------------------------------------------------------


def _load(name: str, raw: bytes | None, kind: type) -> Any:
    if raw is None:
        raise NormalizeError(f"required file missing: {name}")
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise NormalizeError(f"{name}: not valid JSON (or nested too deeply)") from exc
    if not isinstance(data, kind):
        raise NormalizeError(f"{name}: expected a JSON {kind.__name__} at the top level")
    if isinstance(data, dict) and len(data) > MAX_ENTRIES:
        raise NormalizeError(f"{name}: too many entries ({len(data)})")
    return data


def _entries(name: str, data: dict[str, Any], model: type[_M], skipped: list[str]) -> dict[str, _M]:
    out: dict[str, _M] = {}
    for key, value in data.items():
        try:
            out[str(key)] = model.model_validate(value)
        except ValidationError:
            skipped.append(f"{name}/{key}")
    return out


def _check_skipped(skipped: list[str], total: int) -> None:
    limit = max(MAX_SKIPPED_ABSOLUTE, int(total * MAX_SKIPPED_FRACTION))
    if len(skipped) > limit:
        raise NormalizeError(
            f"too many malformed upstream entries ({len(skipped)} of {total}); "
            f"first: {', '.join(skipped[:5])}"
        )


# -- parsing --------------------------------------------------------------------------------------


def parse_enka(files: dict[str, bytes]) -> EnkaRaw:
    skipped: list[str] = []
    affixes_raw = _load("affixes", files.get("affixes"), dict)
    legacy_raw = _load("affixes_legacy", files.get("affixes_legacy"), dict)
    levels_raw = _load("relic_levels", files.get("relic_levels"), dict)
    avatars_raw = _load("avatars", files.get("avatars"), dict)
    weapons_raw = _load("weapons", files.get("weapons"), dict)
    relics_raw = _load("relics", files.get("relics"), dict)
    locs_raw = _load("locs", files.get("locs"), dict)

    levels: dict[str, dict[str, dict[str, float]]] = {}
    for rarity, by_level in levels_raw.items():
        try:
            levels[str(rarity)] = {
                str(lv): {str(p): float(v) for p, v in props.items()}
                for lv, props in by_level.items()
            }
        except (AttributeError, TypeError, ValueError):
            skipped.append(f"relic_levels/{rarity}")

    legacy = {
        k: v.propType
        for k, v in _entries("affixes_legacy", legacy_raw, _RawLegacyAffix, skipped).items()
    }
    en = locs_raw.get("en", {})
    if not isinstance(en, dict):
        raise NormalizeError("locs: 'en' must be an object")
    items_raw = relics_raw.get("Items", {})
    sets_raw = relics_raw.get("Sets", {})
    if not isinstance(items_raw, dict) or not isinstance(sets_raw, dict):
        raise NormalizeError("relics: expected 'Items' and 'Sets' objects")
    for label, coll in (("relics/Items", items_raw), ("relics/Sets", sets_raw), ("locs/en", en)):
        if len(coll) > MAX_ENTRIES:
            raise NormalizeError(f"{label}: too many entries")

    entity_skips: list[str] = []
    avatars = _entries("avatars", avatars_raw, _RawAvatar, entity_skips)
    weapons = _entries("weapons", weapons_raw, _RawWeapon, entity_skips)
    items = _entries("relics/Items", items_raw, _RawItem, entity_skips)
    sets = _entries("relics/Sets", sets_raw, _RawSet, entity_skips)
    total = len(avatars_raw) + len(weapons_raw) + len(items_raw) + len(sets_raw)
    _check_skipped(entity_skips, total)

    return EnkaRaw(
        affixes=_entries("affixes", affixes_raw, _RawAffix, skipped),
        legacy_prop_types=legacy,
        relic_levels=levels,
        avatars=avatars,
        weapons=weapons,
        items=items,
        sets=sets,
        locs_en={str(k): v for k, v in en.items() if isinstance(v, str)},
        skipped=[*skipped, *entity_skips],
        total_entities=total,
    )


def parse_amber(files: dict[str, bytes]) -> AmberRaw:
    curve = _load("reliquaryCurve", files.get("reliquaryCurve"), dict).get("data")
    change = _load("changelog", files.get("changelog"), dict).get("data")
    if not isinstance(curve, dict) or not isinstance(change, dict):
        raise NormalizeError("amber: expected a 'data' object")
    try:
        affix = {
            str(r): {str(s): [float(x) for x in arr] for s, arr in stats.items()}
            for r, stats in curve["affix"].items()
        }
        ranked = {
            str(r): {
                str(lv): {str(s): float(v) for s, v in stats.items()} for lv, stats in lvls.items()
            }
            for r, lvls in curve["ranked"].items()
        }
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise NormalizeError("reliquaryCurve: unexpected structure") from exc
    versions: dict[int, str] = {}
    for key, entry in change.items():
        if key.isdigit() and isinstance(entry, dict) and isinstance(entry.get("version"), str):
            versions[int(key)] = entry["version"]
    return AmberRaw(affix=affix, ranked=ranked, versions=versions)


# -- building -------------------------------------------------------------------------------------


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def _same_values(a: list[float], b: list[float]) -> bool:
    """Multiset equality with float32-style tolerance (upstream has 138.9 vs 138.89999)."""
    return len(a) == len(b) and all(_close(x, y) for x, y in zip(sorted(a), sorted(b), strict=True))


def _derive_prop_names(enka: EnkaRaw, amber: AmberRaw | None, notes: list[str]) -> dict[str, str]:
    names: dict[str, set[str]] = defaultdict(set)
    for affix_id, affix in enka.affixes.items():
        legacy = enka.legacy_prop_types.get(affix_id)
        if legacy:
            names[str(affix.PropType)].add(legacy)
    for prop, found in names.items():
        if len(found) > 1:
            raise NormalizeError(f"prop type {prop} maps to several names: {sorted(found)}")
    resolved = {p: next(iter(f)) for p, f in names.items()}

    if amber is None:
        return resolved
    # Name remaining numeric ids by matching their values across every (rarity, level) with Amber.
    seen: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for rarity, by_level in enka.relic_levels.items():
        for level, props in by_level.items():
            for prop, value in props.items():
                seen[prop].append((rarity, level, value))
    for prop, observations in seen.items():
        candidates: set[str] = set()
        first = True
        for rarity, level, value in observations:
            stats = amber.ranked.get(rarity, {}).get(level, {})
            matching = {s for s, v in stats.items() if _close(v, value)}
            candidates = matching if first else candidates & matching
            first = False
            if not candidates:
                break
        if len(candidates) == 1:
            name = next(iter(candidates))
            if prop in resolved and resolved[prop] != name:
                notes.append(f"prop {prop}: affix join says {resolved[prop]}, values say {name}")
            else:
                resolved.setdefault(prop, name)
        elif len(candidates) > 1:
            notes.append(
                f"prop id {prop} left unnamed: values match {len(candidates)} stats equally"
            )
    return resolved


def _substat_tiers(
    enka: EnkaRaw, prop_names: dict[str, str], notes: list[str]
) -> list[SubstatTier]:
    """Group affixes shaped ``<rarity>01<family code><position>`` by (rarity, PropType).

    The two-digit family code in the middle is NOT the PropType (elemental mastery's differs), so
    it is not interpreted. Only the leading rarity digit and trailing position digit are used; the
    position must match the entry's own ``Position`` and values must rise with position.
    """
    groups: dict[tuple[int, int], list[tuple[int, float, str]]] = defaultdict(list)
    for affix_id, affix in sorted(enka.affixes.items()):
        m = _AFFIX_ID.match(affix_id)
        if not m:
            continue  # not a substat roll tier (other affix families exist upstream)
        rarity, pos = int(m[1]), int(m[3])
        if affix.Position != pos:
            notes.append(f"affix {affix_id} skipped: id position disagrees with its own fields")
            continue
        groups[(rarity, affix.PropType)].append((pos, affix.Value, affix_id))
    tiers: list[SubstatTier] = []
    for (rarity, prop), members in sorted(groups.items()):
        stat = prop_names.get(str(prop))
        if stat is None:
            notes.append(f"rarity {rarity} prop type {prop} skipped: no name in the data")
            continue
        members.sort()
        positions = [p for p, _, _ in members]
        values = [v for _, v, _ in members]
        if positions != list(range(1, len(members) + 1)) or any(
            b <= a for a, b in itertools.pairwise(values)
        ):
            notes.append(
                f"rarity {rarity} {stat} skipped: positions/values are not a rising 1..n run"
            )
            continue
        for pos, value, affix_id in members:
            try:
                tiers.append(
                    SubstatTier(
                        affix_id=affix_id, rarity=rarity, stat=stat, position=pos, value=value
                    )
                )
            except ValidationError:
                notes.append(f"affix {affix_id} skipped: value out of range")
    return tiers


def _crosscheck_tiers(
    tiers: list[SubstatTier], amber: AmberRaw | None, notes: list[str]
) -> Confidence:
    if amber is None:
        notes.append("substat tiers: no cross-check source available (single source)")
        return "provisional"
    by_key: dict[tuple[int, str], list[SubstatTier]] = defaultdict(list)
    for t in tiers:
        by_key[(t.rarity, t.stat)].append(t)
    compared, ok = 0, True
    for (rarity, stat), group in sorted(by_key.items()):
        theirs = amber.affix.get(str(rarity), {}).get(stat)
        if theirs is None:
            continue  # Amber does not list it; not a disagreement, just not cross-checked
        compared += 1
        mine = [t.value for t in sorted(group, key=lambda t: t.position)]
        if len(mine) != len(theirs) or not all(
            _close(a, b) for a, b in zip(mine, theirs, strict=True)
        ):
            ok = False
            notes.append(
                f"substat tiers disagree for rarity {rarity} {stat}: enka={mine} amber={theirs}"
            )
    if compared == 0:
        notes.append("substat tiers: cross-check source shared no (rarity, stat) pairs")
        return "provisional"
    return "curated" if ok else "provisional"


def _main_stats(
    enka: EnkaRaw, amber: AmberRaw | None, prop_names: dict[str, str], notes: list[str]
) -> tuple[list[MainStatValue], Confidence]:
    out: list[MainStatValue] = []
    if amber is not None:
        agree, compared = True, 0
        for rarity, by_level in sorted(amber.ranked.items()):
            for level_key, stats in sorted(by_level.items(), key=lambda kv: int(kv[0])):
                level = int(level_key) - 1
                for stat, value in sorted(stats.items()):
                    if _FIGHT_PROP.match(stat) and value > 0 and 0 <= level <= 20:
                        out.append(
                            MainStatValue(rarity=int(rarity), level=level, stat=stat, value=value)
                        )
                theirs = enka.relic_levels.get(rarity, {}).get(level_key)
                if theirs is not None:
                    compared += 1
                    if not _same_values(list(theirs.values()), list(stats.values())):
                        agree = False
                        notes.append(
                            f"main stat values disagree at rarity {rarity} level key {level_key}"
                        )
        if compared == 0:
            notes.append("main stats: cross-check source shared no (rarity, level) pairs")
        return out, "curated" if agree and compared else "provisional"
    # Single-source fallback: only ids we could name from data.
    unnamed: set[str] = set()
    for rarity, by_level in sorted(enka.relic_levels.items()):
        for level_key, props in sorted(by_level.items(), key=lambda kv: int(kv[0])):
            for prop, value in sorted(props.items()):
                named = prop_names.get(prop)
                if named is None:
                    unnamed.add(prop)
                    continue
                out.append(
                    MainStatValue(
                        rarity=int(rarity), level=int(level_key) - 1, stat=named, value=value
                    )
                )
    if unnamed:
        notes.append(
            f"main stats: prop ids without a name were omitted: {sorted(unnamed, key=int)}"
        )
    notes.append("main stats: no cross-check source available (single source)")
    return out, "provisional"


def _game_version(amber: AmberRaw | None, notes: list[str]) -> str:
    if amber is None or not amber.versions:
        notes.append("game version unknown: no changelog source available")
        return "unknown"
    version = amber.versions[max(amber.versions)]
    if not _VERSION.match(version):
        notes.append("game version unknown: changelog version string is not a plain 'N.N'")
        return "unknown"
    return version


def build_snapshot(
    enka: EnkaRaw,
    amber: AmberRaw | None,
    *,
    sources: list[SourceRecord],
    fetched_at: datetime,
) -> Snapshot:
    notes: list[str] = [f"skipped upstream entry: {s}" for s in sorted(enka.skipped)]
    prop_names = _derive_prop_names(enka, amber, notes)
    tiers = _substat_tiers(enka, prop_names, notes)
    tier_conf = _crosscheck_tiers(tiers, amber, notes)
    main, main_conf = _main_stats(enka, amber, prop_names, notes)
    loc = enka.locs_en

    characters = [
        Character(
            id=cid,
            name=loc.get(str(a.NameTextMapHash)),
            element=a.Element,
            weapon_type=a.WeaponType,
            quality=a.QualityType,
            base_props=a.BaseProps,
        )
        for cid, a in sorted(enka.avatars.items())
    ]
    weapons = [
        Weapon(
            id=wid,
            name=loc.get(str(w.NameTextMapHash)),
            rarity=w.Rarity,
            weapon_type=w.WeaponType,
            base_props=w.BaseProps,
        )
        for wid, w in sorted(enka.weapons.items())
    ]
    sets = [
        ArtifactSet(id=sid, name=loc.get(s.Name), add_props=s.AddProps)
        for sid, s in sorted(enka.sets.items())
    ]
    pieces = [
        ArtifactPiece(id=iid, rarity=i.Rarity, equip_type=i.EquipType, set_id=str(i.SetId))
        for iid, i in sorted(enka.items.items())
    ]
    return Snapshot(
        game_version=_game_version(amber, notes),
        fetched_at=fetched_at,
        sources=sources,
        confidence={
            "substat_tiers": tier_conf,
            "main_stats": main_conf,
            "characters": "provisional",
            "weapons": "provisional",
            "artifact_sets": "provisional",
        },
        notes=notes,
        prop_names=dict(sorted(prop_names.items(), key=lambda kv: int(kv[0]))),
        substat_tiers=tiers,
        main_stats=main,
        characters=characters,
        weapons=weapons,
        artifact_sets=sets,
        artifacts=pieces,
    )
