"""The `recommend` report: what each character's profile recommends, how the equipped build
compares, and what to fix first. Maps roster types to the pure advice rules in
``builds.recommend`` and formats text. Every number comes from the scoring engine, the profiles or
the data snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from genshin_companion.app.report import render_profile, stat_label
from genshin_companion.app.score import _safe, score_roster
from genshin_companion.builds.profiles import CharacterProfile
from genshin_companion.builds.recommend import Advice, PieceView, advise
from genshin_companion.data.models import Snapshot
from genshin_companion.enka.models import Roster
from genshin_companion.scoring import ArtifactRules

WeaponStatus = Literal["best", "alternative", "not_listed", "no_list", "unknown"]


@dataclass(frozen=True, slots=True)
class CharacterRecommendation:
    avatar_id: int
    name: str
    level: int
    constellation: int
    profile: CharacterProfile | None
    data_version: str
    pieces: tuple[PieceView, ...] = ()
    advice: tuple[Advice, ...] = ()
    weapon_name: str | None = None
    weapon_refinement: int | None = None
    weapon_status: WeaponStatus = "unknown"
    notes: tuple[str, ...] = ()


def _weapon(chosen: CharacterProfile, weapon_name: str | None) -> WeaponStatus:
    if weapon_name is None:
        return "unknown"
    if not chosen.recommended_weapons:
        return "no_list"
    for w in chosen.recommended_weapons:
        if w.name == weapon_name:
            return w.tier
    return "not_listed"


def recommend_roster(
    roster: Roster,
    snapshot: Snapshot,
    profiles: list[CharacterProfile],
    rules: ArtifactRules | None = None,
) -> list[CharacterRecommendation]:
    weapons = {w.id: w.name for w in snapshot.weapons}
    results = score_roster(roster, snapshot, profiles, rules)
    out: list[CharacterRecommendation] = []
    for ch, res in zip(roster.characters, results, strict=True):
        assert res.avatar_id == ch.avatar_id
        weapon_name = weapons.get(str(ch.weapon.item_id)) if ch.weapon else None
        refinement = ch.weapon.refinement if ch.weapon and weapon_name else None
        if res.chosen is None:
            out.append(
                CharacterRecommendation(
                    ch.avatar_id, res.name, ch.level, ch.constellation, None, snapshot.game_version
                )
            )
            continue
        pieces = tuple(
            PieceView(p.slot, p.level, p.rarity, p.main_stat, p.set_name, p.score)
            for p in res.pieces
        )
        out.append(
            CharacterRecommendation(
                avatar_id=ch.avatar_id,
                name=res.name,
                level=ch.level,
                constellation=ch.constellation,
                profile=res.chosen,
                data_version=snapshot.game_version,
                pieces=pieces,
                advice=tuple(advise(res.chosen, list(pieces), weapon_name)),
                weapon_name=_safe(weapon_name) if weapon_name else None,
                weapon_refinement=refinement,
                weapon_status=_weapon(res.chosen, weapon_name),
                notes=res.notes,
            )
        )
    return out


def _stats(stats: tuple[str, ...]) -> str:
    return ", ".join(stat_label(s) for s in stats) or "(nothing recorded)"


def _advice_text(a: Advice) -> str:
    slot = a.slot or ""
    if a.kind == "missing":
        return f"{slot}: no piece equipped"
    if a.kind == "main_stat":
        wanted = f"; recommended: {_stats(a.recommended)}" if a.recommended else ""
        label = stat_label(a.main_stat or "")
        return f"{slot}: main stat {label} is not on the recommended list{wanted}"
    if a.kind == "set":
        name = _safe(a.set_name) if a.set_name else "an unknown set"
        wanted = "; recommended: " + ", ".join(_safe(r) for r in a.recommended)
        return f"{slot}: {name} is not a recommended set{wanted}"
    if a.kind == "rolls":
        level = a.level or 0
        upgrading = f" (+{level}, still being upgraded)" if level < 20 else f" (+{level})"
        return (
            f"weakest substat rolls: {slot}{upgrading}, "
            f"{(a.value or 0.0):.2f} of a perfect roll per roll on average"
        )
    if a.kind == "level_up":
        ceiling = f"up to {a.ceiling:.2f} at best" if a.ceiling is not None else "upgrade"
        share = f" ({a.pct_ceiling:.0%} of the maximum)" if a.pct_ceiling is not None else ""
        return (
            f"level up: {slot} (+{a.level}): {(a.value or 0.0):.2f} per roll so far, "
            f"{ceiling}{share}"
        )
    return "weapon: not on the researched list; recommended: " + ", ".join(
        _safe(r) for r in a.recommended
    )


def _advice_lines(advice: list[Advice]) -> list[str]:
    """One line per piece of advice, except that several wrong-set pieces share a single line."""
    sets = [a for a in advice if a.kind == "set"]
    lines: list[str] = []
    grouped = False
    for a in advice:
        if a.kind != "set" or len(sets) == 1:
            lines.append(_advice_text(a))
        elif not grouped:
            grouped = True
            parts = ", ".join(f"{x.slot} ({_safe(x.set_name or 'unknown')})" for x in sets)
            wanted = ", ".join(_safe(r) for r in sets[0].recommended)
            lines.append(f"sets: {parts} are not recommended sets; recommended: {wanted}")
    return lines


_WEAPON_TEXT = {
    "best": "recommended (best)",
    "alternative": "recommended (alternative)",
    "not_listed": "not on the researched list",
    "no_list": "no weapon list recorded for this character",
    "unknown": "weapon not recognised in the data",
}


def render_recommendations(recs: list[CharacterRecommendation]) -> str:
    out: list[str] = []
    for r in recs:
        out.append(f"\n{r.name}  Lv{r.level}  C{r.constellation}")
        if r.profile is None:
            out.append("  no profile recorded for this character: nothing to recommend")
            continue
        p = r.profile
        out.append(
            f"  [{p.confidence}, {p.kind} profile read {p.observed_at}, game data {r.data_version}]"
        )
        # the profile block (sets, weapons, main stats, substats, notes, sources) without its title
        out.extend(render_profile(p).split("\n")[1:])
        if r.weapon_name:
            refine = f" (R{r.weapon_refinement})" if r.weapon_refinement else ""
            status = _WEAPON_TEXT[r.weapon_status]
            out.append(f"  equipped weapon: {r.weapon_name}{refine}: {status}")
        else:
            out.append("  equipped weapon: none imported")
        out.append("  what to do first:")
        lines = _advice_lines(list(r.advice))
        out.extend(f"    {i}. {line}" for i, line in enumerate(lines, 1))
        if not lines:
            out.append("    nothing to flag")
        out.extend(f"  note: {_safe(n, 300)}" for n in r.notes)
    return "\n".join(out).lstrip("\n")
