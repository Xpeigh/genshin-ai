"""Piece scoring (docs/scoring-spec.md). Pure and deterministic: same input + same snapshot = same
output. Nothing here reads files, clocks, randomness or the network.

A roll's value is its tier value divided by the best FIVE-star tier value of that stat, so a perfect
five-star roll is 1.0 and a lower-rarity roll is worth proportionally less. A roll's weight comes
from the profile. The roll score is the sum of weight x value over the piece's valid rolls.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Final

from genshin_companion.data.models import Confidence, Snapshot
from genshin_companion.scoring.models import (
    ArtifactInput,
    ArtifactScore,
    MainStatFit,
    NotScored,
    Provenance,
    ScoringProfile,
    SetFit,
    StatBreakdown,
)

CRIT_RATE: Final = "FIGHT_PROP_CRITICAL"
CRIT_DMG: Final = "FIGHT_PROP_CRITICAL_HURT"
FIXED_SLOTS: Final = frozenset({"flower", "plume"})
_CONFIDENCE_RANK: Final[dict[str, int]] = {"provisional": 0, "curated": 1, "verified": 2}


def _weakest(a: Confidence, b: Confidence) -> Confidence:
    return a if _CONFIDENCE_RANK[a] <= _CONFIDENCE_RANK[b] else b


def _main_stat_fit(art: ArtifactInput, profile: ScoringProfile) -> MainStatFit:
    if art.slot in FIXED_SLOTS:
        return MainStatFit(status="fixed")
    listed = profile.main_stats.get(art.slot)
    if not listed:
        return MainStatFit(status="unknown")
    matches = [m for m in listed if m.stat == art.main_stat]
    plain = next((m for m in matches if m.condition is None), None)
    if plain is not None:
        return MainStatFit(status="recommended", usage_percent=plain.usage_percent)
    if matches:
        return MainStatFit(
            status="conditional",
            usage_percent=matches[0].usage_percent,
            condition=matches[0].condition,
        )
    return MainStatFit(status="not_listed")


def _set_fit(art: ArtifactInput, profile: ScoringProfile) -> SetFit:
    if art.set_name is None:
        return SetFit(status="other")
    containing = [(i, o) for i, o in enumerate(profile.sets) if art.set_name in o.sets]
    if not containing:
        return SetFit(status="other")
    # an unconditional listing beats a conditional one (as for main stats), then best beats
    # alternative, then the first listed
    _, chosen = min(
        containing, key=lambda io: (io[1].condition is not None, io[1].tier != "best", io[0])
    )
    return SetFit(
        status=chosen.tier, usage_percent=chosen.usage_percent, condition=chosen.condition
    )


def score_artifact(
    art: ArtifactInput, profile: ScoringProfile, snapshot: Snapshot
) -> ArtifactScore:
    tiers = {t.affix_id: t for t in snapshot.substat_tiers}
    best_five: dict[str, float] = {}
    for t in snapshot.substat_tiers:
        if t.rarity == 5:
            best_five[t.stat] = max(best_five.get(t.stat, 0.0), t.value)

    problems: list[str] = []
    values: dict[str, list[float]] = defaultdict(list)
    for affix_id in art.roll_affix_ids:
        tier = tiers.get(affix_id)
        if tier is None:
            problems.append(f"roll id {affix_id} is not in the data snapshot; not scored")
        elif tier.rarity != art.rarity:
            problems.append(
                f"roll id {affix_id} is a rarity-{tier.rarity} roll on a rarity-{art.rarity} "
                "piece; not scored"
            )
        elif tier.stat == art.main_stat:
            problems.append(
                f"a roll on the piece's own main stat ({tier.stat}) cannot exist; not scored"
            )
        elif tier.stat not in best_five:
            problems.append(f"no five-star reference roll for {tier.stat} in the data; not scored")
        else:
            values[tier.stat].append(tier.value)

    breakdown: list[StatBreakdown] = []
    not_scored: list[NotScored] = []
    for stat in sorted(values):
        vals = tuple(sorted(values[stat]))
        weight = profile.weights.get(stat, 0.0)
        contribution = weight * math.fsum(v / best_five[stat] for v in vals)
        breakdown.append(
            StatBreakdown(
                stat=stat, rolls=len(vals), values=vals, weight=weight, contribution=contribution
            )
        )
        if stat in profile.unscored:
            not_scored.append(
                NotScored(stat=stat, condition=profile.unscored[stat], rolls=len(vals))
            )

    total_rolls = sum(b.rolls for b in breakdown)
    useful_rolls = sum(b.rolls for b in breakdown if b.weight > 0)
    # math.fsum is exactly rounded, so no sum depends on the order the rolls arrived in
    roll_score = math.fsum(b.contribution for b in breakdown)
    crit_value = 2 * 100 * math.fsum(values.get(CRIT_RATE, [])) + 100 * math.fsum(
        values.get(CRIT_DMG, [])
    )

    data_confidence = snapshot.confidence.get("substat_tiers", "provisional")
    if art.set_name is not None:  # the set name came from the set data
        sets_confidence = snapshot.confidence.get("artifact_sets", "provisional")
        data_confidence = _weakest(data_confidence, sets_confidence)
    return ArtifactScore(
        roll_score=roll_score,
        total_rolls=total_rolls,
        useful_rolls=useful_rolls,
        average_per_roll=roll_score / total_rolls if total_rolls else 0.0,
        stats=tuple(breakdown),
        not_scored=tuple(not_scored),
        crit_value=crit_value,
        main_stat_fit=_main_stat_fit(art, profile),
        set_fit=_set_fit(art, profile),
        problems=tuple(problems),
        provenance=Provenance(
            profile_kind=profile.kind,
            profile_source=profile.source,
            profile_observed_at=profile.observed_at,
            data_version=snapshot.game_version,
            confidence=_weakest(profile.confidence, data_confidence),
            weights_note=profile.weights_note,
        ),
    )
