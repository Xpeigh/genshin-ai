"""Per-character summary of piece scores. Pure: it only combines ``ArtifactScore`` values."""

from __future__ import annotations

import math
from typing import Final

from genshin_companion.scoring.models import ArtifactScore, Slot, _Frozen

SLOT_ORDER: Final[tuple[Slot, ...]] = ("flower", "plume", "sands", "goblet", "circlet")
TIE_DECIMALS: Final = 9  # scores closer than this are a tie, so one float bit never decides


class CharacterSummary(_Frozen):
    pieces_scored: int
    missing_slots: tuple[Slot, ...]
    total_roll_score: float
    weakest_slot: Slot | None  # lowest roll score; ties go to the earlier slot in game order
    strongest_slot: Slot | None
    main_stat_not_listed: tuple[Slot, ...]  # main stat positively absent from the profile's list
    recommended_set_pieces: int  # pieces in a best or alternative set


def summarize_character(scores: dict[Slot, ArtifactScore]) -> CharacterSummary:
    present = [slot for slot in SLOT_ORDER if slot in scores]

    def level(s: Slot) -> float:
        return round(scores[s].roll_score, TIE_DECIMALS)

    weakest = min(present, key=lambda s: (level(s), SLOT_ORDER.index(s)), default=None)
    strongest = max(present, key=lambda s: (level(s), -SLOT_ORDER.index(s)), default=None)
    return CharacterSummary(
        pieces_scored=len(present),
        missing_slots=tuple(s for s in SLOT_ORDER if s not in scores),
        total_roll_score=math.fsum(scores[s].roll_score for s in present),
        weakest_slot=weakest,
        strongest_slot=strongest,
        main_stat_not_listed=tuple(
            s for s in present if scores[s].main_stat_fit.status == "not_listed"
        ),
        recommended_set_pieces=sum(1 for s in present if scores[s].set_fit.status != "other"),
    )
