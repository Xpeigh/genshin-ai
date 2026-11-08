"""Turn a curated profile into the plain numbers the scoring engine takes (docs/scoring-spec.md).

``scoring`` cannot read profiles, so this is where profile tiers become weights. The rule:

- tier 0 weighs 1.0 and each further tier weighs 0.25 less, never below 0.25 (a convention, not game
  data: ``TIER_STEP`` and ``MIN_TIER_WEIGHT``); stats tied in one tier share its weight. An in-game
  profile has one tier (an unordered favoured set), so all its stats weigh 1.0.
- a conditional stat is NOT scored (weight 0) and is handed over with its condition so the result
  can say so; it still occupies its tier so the stats ranked below it keep their weight.
"""

from __future__ import annotations

from typing import Final

from genshin_companion.builds.profiles import CharacterProfile
from genshin_companion.scoring import (
    RecommendedMainStat,
    RecommendedSet,
    ScoringProfile,
)

TIER_STEP: Final = 0.25
MIN_TIER_WEIGHT: Final = 0.25
TIER_NOTE: Final = (
    "Tier weights (1.0, 0.75, 0.5, then 0.25) are a convention chosen with Ben, not game data."
)


def tier_weight(index: int) -> float:
    return max(MIN_TIER_WEIGHT, 1.0 - TIER_STEP * index)


def to_scoring_profile(profile: CharacterProfile) -> ScoringProfile:
    weights: dict[str, float] = dict(profile.substat_weights)
    unscored: dict[str, str] = {}
    for index, tier in enumerate(profile.substat_tiers):
        for choice in tier:
            if choice.condition is not None:
                unscored[choice.stat] = choice.condition
            elif profile.kind == "in-game":
                weights[choice.stat] = 1.0  # an unordered favoured set, whatever its tiers
            else:
                weights[choice.stat] = tier_weight(index)
    return ScoringProfile(
        character_id=profile.character_id,
        character_name=profile.name,
        kind=profile.kind,
        source=profile.source,
        observed_at=profile.observed_at.isoformat(),
        confidence=profile.confidence,
        weights=weights,
        unscored=unscored,
        main_stats={
            slot: [
                RecommendedMainStat(
                    stat=c.stat, usage_percent=c.usage_percent, condition=c.condition
                )
                for c in choices
            ]
            for slot, choices in profile.recommended_main_stats.items()
        },
        sets=tuple(
            RecommendedSet(
                sets=tuple(o.sets),
                tier=o.tier,
                usage_percent=o.usage_percent,
                condition=o.condition,
            )
            for o in profile.recommended_sets
        ),
        weights_note=TIER_NOTE if profile.kind == "guide" else None,
    )


def select_profile(profiles: list[CharacterProfile], character_id: str) -> CharacterProfile | None:
    """The profile to score a character with: the in-game one if there is one, else the guide's.

    An exact id wins. A profile keyed per variant (``10000007-705``) answers for its base avatar
    (``10000007``) only when exactly one variant exists, because the roster does not record which
    variant (element) a Traveler is; the caller flags that.
    """

    def best(found: list[CharacterProfile]) -> CharacterProfile | None:
        return min(found, key=lambda p: p.kind != "in-game", default=None)

    exact = [p for p in profiles if p.character_id == character_id]
    if exact:
        return best(exact)
    variants = [p for p in profiles if p.character_id.startswith(character_id + "-")]
    if len({p.character_id for p in variants}) != 1:
        return None  # none, or several variants and the roster cannot say which one
    return best(variants)
