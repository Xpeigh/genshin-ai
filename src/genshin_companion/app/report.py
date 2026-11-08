"""Plain-text roster report. Presentation only; all numbers come from the import and snapshot."""

from __future__ import annotations

from genshin_companion.builds.profiles import CharacterProfile, StatChoice
from genshin_companion.data.models import Snapshot, SubstatTier
from genshin_companion.enka.models import ImportedArtifact, Roster
from genshin_companion.enka.verify import check_artifact, tier_index

SLOTS = {
    "EQUIP_BRACER": "Flower",
    "EQUIP_NECKLACE": "Plume",
    "EQUIP_SHOES": "Sands",
    "EQUIP_RING": "Goblet",
    "EQUIP_DRESS": "Circlet",
}


# Display names as listed in Enka's AppendProp table (docs/gi/api.md).
STAT_NAMES = {
    "FIGHT_PROP_BASE_ATTACK": "Base ATK",
    "FIGHT_PROP_HP": "HP",
    "FIGHT_PROP_ATTACK": "ATK",
    "FIGHT_PROP_DEFENSE": "DEF",
    "FIGHT_PROP_HP_PERCENT": "HP%",
    "FIGHT_PROP_ATTACK_PERCENT": "ATK%",
    "FIGHT_PROP_DEFENSE_PERCENT": "DEF%",
    "FIGHT_PROP_CRITICAL": "CRIT Rate",
    "FIGHT_PROP_CRITICAL_HURT": "CRIT DMG",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "Energy Recharge",
    "FIGHT_PROP_HEAL_ADD": "Healing Bonus",
    "FIGHT_PROP_ELEMENT_MASTERY": "Elemental Mastery",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "Physical DMG Bonus",
    "FIGHT_PROP_FIRE_ADD_HURT": "Pyro DMG Bonus",
    "FIGHT_PROP_ELEC_ADD_HURT": "Electro DMG Bonus",
    "FIGHT_PROP_WATER_ADD_HURT": "Hydro DMG Bonus",
    "FIGHT_PROP_WIND_ADD_HURT": "Anemo DMG Bonus",
    "FIGHT_PROP_ICE_ADD_HURT": "Cryo DMG Bonus",
    "FIGHT_PROP_ROCK_ADD_HURT": "Geo DMG Bonus",
    "FIGHT_PROP_GRASS_ADD_HURT": "Dendro DMG Bonus",
}


def stat_label(stat: str) -> str:
    return STAT_NAMES.get(stat, stat.removeprefix("FIGHT_PROP_").replace("_", " ").title())


def _artifact_lines(
    art: ImportedArtifact, snapshot: Snapshot | None, idx: dict[str, SubstatTier]
) -> list[str]:
    slot = SLOTS.get(art.slot, art.slot)
    head = (
        f"    {slot:<8} +{art.level} {art.rarity}*  {stat_label(art.main_stat)} {art.main_value:g}"
    )
    if snapshot is not None and art.set_id is not None:
        name = next((s.name for s in snapshot.artifact_sets if s.id == str(art.set_id)), None)
        if name:
            head += f"  [{name}]"
    lines = [head]
    check = check_artifact(art, snapshot, idx) if snapshot is not None else None
    for sub in art.substats:
        rolls = check.rolls.get(sub.stat, []) if check else []
        suffix = f"  rolls: {len(rolls)} (tiers {', '.join(map(str, rolls))})" if rolls else ""
        lines.append(f"      - {stat_label(sub.stat):<20} {sub.value:g}{suffix}")
    if check is None:
        lines.append("      (no data snapshot yet: run `genshin-companion sync` to verify rolls)")
    elif not check.ok:
        lines.extend(f"      ! CHECK FAILED: {p}" for p in check.problems)
    return lines


def render_roster(roster: Roster, snapshot: Snapshot | None) -> str:
    chars = {c.id: c for c in snapshot.characters} if snapshot else {}
    weapons = {w.id: w for w in snapshot.weapons} if snapshot else {}
    idx = tier_index(snapshot) if snapshot else {}
    who = f" ({roster.nickname}, AR {roster.player_level})" if roster.nickname else ""
    out = [
        f"Roster for UID {roster.uid}{who}",
        f"  source: {roster.source}, fetched {roster.fetched_at.isoformat()}, ttl {roster.ttl}s",
        f"  game data: {'version ' + snapshot.game_version if snapshot else 'no snapshot'}",
    ]
    for ch in roster.characters:
        known = chars.get(str(ch.avatar_id))
        name = (known.name if known and known.name else None) or f"avatar {ch.avatar_id}"
        out.append(f"\n  {name}  Lv{ch.level}  C{ch.constellation}")
        if ch.weapon:
            w = weapons.get(str(ch.weapon.item_id))
            wname = (w.name if w and w.name else None) or f"weapon {ch.weapon.item_id}"
            out.append(f"    Weapon   {wname} Lv{ch.weapon.level} R{ch.weapon.refinement}")
        for art in ch.artifacts:
            out.extend(_artifact_lines(art, snapshot, idx))
    out.append("")
    out.extend(f"  note: {n}" for n in roster.notes)
    return "\n".join(out)


def _choice(choice: StatChoice) -> str:
    label = stat_label(choice.stat)
    return f"{label} ({choice.condition})" if choice.condition else label


def render_profile(p: CharacterProfile) -> str:
    """One profile as plain text; conditions stay visible so no ranking looks unconditional."""
    out = [
        f"{p.name} ({p.character_id}) [{p.confidence}, {p.kind}] "
        f"read {p.observed_at} at game {p.game_version}"
    ]
    if p.role:
        out.append(f"    role: {p.role}")
    if p.substat_tiers:
        ranking = " > ".join(" / ".join(_choice(c) for c in tier) for tier in p.substat_tiers)
        out.append(f"    substats: {ranking}")
    else:
        weights = ", ".join(f"{stat_label(k)}={v:g}" for k, v in p.substat_weights.items())
        out.append(f"    substats: {weights}")
    if p.recommended_sets:
        for option in p.recommended_sets:
            pct = option.usage_percent
            share = f", {pct:g}% of players" if pct is not None else ""
            why = f": {option.condition}" if option.condition else ""
            out.append(f"    set: {' + '.join(option.sets)} ({option.tier}{share}{why})")
    else:
        out.append("    sets: (not recorded)")
    if p.recommended_main_stats:
        for slot, choices in p.recommended_main_stats.items():
            out.append(f"    {slot}: {', '.join(_choice(c) for c in choices)}")
    else:
        out.append("    main stats: (not recorded)")
    out.extend(f"    note: {n}" for n in p.notes)
    out.extend(f"    source: {r.name}" for r in p.references)
    return "\n".join(out)
