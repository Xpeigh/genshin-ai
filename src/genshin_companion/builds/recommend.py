"""What to fix first on a character's build (Phase 4). Pure: a profile, the scored pieces and the
equipped weapon in, ordered advice out. Every number comes from the scoring engine or the profile;
this module only decides what is worth mentioning and in which order.

Priorities (1 = do first): a missing piece, a main stat that is not on the recommended list, a piece
from a set the profile does not recommend, the weakest substat rolls among the remaining pieces,
and (for information) an equipped weapon that is not on the researched list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from genshin_companion.builds.profiles import CharacterProfile
from genshin_companion.scoring import ArtifactScore
from genshin_companion.scoring.character import SLOT_ORDER
from genshin_companion.scoring.models import Slot

Kind = Literal["missing", "main_stat", "set", "rolls", "level_up", "weapon"]

PRIORITY: Final[dict[Kind, int]] = {
    "missing": 1,
    "main_stat": 2,
    "set": 3,
    "rolls": 4,
    "level_up": 5,
    "weapon": 6,
}
MAX_LEVEL_UP: Final = 2  # pieces named as worth upgrading
MAX_LISTED: Final = 3  # recommended sets or weapons named in one piece of advice


@dataclass(frozen=True, slots=True)
class PieceView:
    slot: Slot
    level: int
    rarity: int
    main_stat: str
    set_name: str | None
    score: ArtifactScore


@dataclass(frozen=True, slots=True)
class Advice:
    priority: int
    kind: Kind
    slot: Slot | None = None
    main_stat: str | None = None
    set_name: str | None = None
    recommended: tuple[str, ...] = ()  # stat ids, set names or weapon names, best first
    level: int | None = None
    value: float | None = None  # average roll value, for "rolls" and "level_up"
    ceiling: float | None = None  # best-case roll score after upgrading, for "level_up"
    pct_ceiling: float | None = None  # that ceiling as a share of the theoretical maximum


def _recommended_sets(profile: CharacterProfile) -> tuple[str, ...]:
    ordered = sorted(profile.recommended_sets, key=lambda o: o.tier != "best")  # stable: best first
    names: list[str] = []
    for option in ordered:
        text = " + ".join(option.sets)
        if text not in names:
            names.append(text)
    return tuple(names[:MAX_LISTED])


def advise(
    profile: CharacterProfile, pieces: list[PieceView], weapon_name: str | None
) -> list[Advice]:
    by_slot = {p.slot: p for p in pieces}
    advice: list[Advice] = []
    flagged: set[Slot] = set()

    for slot in SLOT_ORDER:
        if slot not in by_slot:
            advice.append(Advice(PRIORITY["missing"], "missing", slot=slot))

    for slot in SLOT_ORDER:
        piece = by_slot.get(slot)
        if piece is None:
            continue
        if piece.score.main_stat_fit.status == "not_listed":
            wanted = tuple(
                c.stat for c in profile.recommended_main_stats.get(slot, []) if c.condition is None
            )
            advice.append(
                Advice(
                    PRIORITY["main_stat"],
                    "main_stat",
                    slot=slot,
                    main_stat=piece.main_stat,
                    recommended=wanted,
                )
            )
            flagged.add(slot)
        if profile.recommended_sets and piece.score.set_fit.status == "other":
            advice.append(
                Advice(
                    PRIORITY["set"],
                    "set",
                    slot=slot,
                    set_name=piece.set_name,
                    recommended=_recommended_sets(profile),
                )
            )
            flagged.add(slot)

    # An un-upgraded piece has few rolls, so rank by the average roll, never by the total.
    candidates = [p for p in pieces if p.slot not in flagged and p.score.total_rolls > 0]
    if candidates:
        weakest = min(
            candidates, key=lambda p: (p.score.average_per_roll, SLOT_ORDER.index(p.slot))
        )
        advice.append(
            Advice(
                PRIORITY["rolls"],
                "rolls",
                slot=weakest.slot,
                level=weakest.level,
                value=weakest.score.average_per_roll,
            )
        )

    # Spend upgrade resources where the rolls are already good: pieces whose main stat and set are
    # fine, that can still be upgraded and already have at least one useful roll.
    levelable = [
        p
        for p in pieces
        if p.slot not in flagged
        and p.score.potential.status == "modelled"
        and (p.score.potential.upgrades_left or 0) > 0
        and p.score.total_rolls > 0
        and p.score.average_per_roll > 0
    ]
    levelable.sort(key=lambda p: (-p.score.average_per_roll, SLOT_ORDER.index(p.slot)))
    for p in levelable[:MAX_LEVEL_UP]:
        advice.append(
            Advice(
                PRIORITY["level_up"],
                "level_up",
                slot=p.slot,
                level=p.level,
                value=p.score.average_per_roll,
                ceiling=p.score.potential.ceiling,
                pct_ceiling=p.score.potential.pct_ceiling_of_max,
            )
        )

    if weapon_name is not None and profile.recommended_weapons:
        listed = {w.name for w in profile.recommended_weapons}
        if weapon_name not in listed:
            ordered = sorted(profile.recommended_weapons, key=lambda w: w.tier != "best")
            advice.append(
                Advice(
                    PRIORITY["weapon"],
                    "weapon",
                    recommended=tuple(w.name for w in ordered[:MAX_LISTED]),
                )
            )

    advice.sort(key=lambda a: (a.priority, SLOT_ORDER.index(a.slot) if a.slot else len(SLOT_ORDER)))
    return advice
