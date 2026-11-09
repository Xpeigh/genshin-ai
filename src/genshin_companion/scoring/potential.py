"""Potential of an artifact piece (docs/potential-spec.md): what upgrading can still add, and how
the piece compares with the best possible one. Pure arithmetic over the snapshot's tier values and
the profile's weights; no odds are used, so there is no expected value, only a floor, a best-case
ceiling and percentages of two theoretical maxima.

Structure assumed (each fact is checked against real pieces; see the spec): one roll every 4 levels;
a piece starts with at most (rarity - 1) substats and every upgrade activates a new substat until it
shows 4, then upgrades an existing one; the main stat is never a substat.
"""

from __future__ import annotations

from collections.abc import Iterable

from genshin_companion.data.models import SubstatTier
from genshin_companion.scoring.models import ArtifactInput, ArtifactRules, Potential

UPGRADE_EVERY = 4
MAX_SUBSTATS = 4


def _not_modelled(reason: str) -> Potential:
    return Potential(status="not_modelled", reason=reason)


def _pct(part: float, whole: float) -> float | None:
    return part / whole if whole > 0 else None


def compute_potential(
    art: ArtifactInput,
    weights: dict[str, float],
    tiers: Iterable[SubstatTier],
    best_five: dict[str, float],
    present: set[str],
    current: float,
    rules: ArtifactRules | None,
) -> Potential:
    if rules is None:
        return _not_modelled("no artifact level rules were supplied")
    max_level = rules.max_level.get(art.rarity)
    if max_level is None:
        return _not_modelled(f"the maximum level of {art.rarity}-star pieces is not known")

    # value of a perfect (top-tier) roll of each eligible stat at this rarity, times its weight
    top: dict[str, float] = {}
    for t in tiers:
        if t.rarity == art.rarity and t.stat in best_five and t.stat != art.main_stat:
            top[t.stat] = max(top.get(t.stat, 0.0), t.value / best_five[t.stat])
    value = {stat: weights.get(stat, 0.0) * ratio for stat, ratio in top.items()}
    ranked = sorted(value.values(), reverse=True)
    best = ranked[0] if ranked else 0.0

    problems: list[str] = []
    assumptions: list[str] = []
    total_upgrades = max_level // UPGRADE_EVERY
    done = art.level // UPGRADE_EVERY
    if art.level > max_level:
        problems.append(
            f"level {art.level} is above the maximum {max_level} for {art.rarity}-star pieces"
        )
        done = total_upgrades
    left = total_upgrades - done

    def best_piece(upgrades: int) -> float:
        """The best possible piece after ``upgrades`` upgrades (it starts with rarity - 1 stats)."""
        start = min(art.rarity - 1, len(ranked))
        activated = min(upgrades, MAX_SUBSTATS - start, len(ranked) - start)
        return sum(ranked[: start + activated]) + (upgrades - activated) * best

    maximum = best_piece(total_upgrades)
    maximum_now = best_piece(done)

    # ceiling: the best case for the remaining upgrades from this piece's actual substats
    shown = len(present)
    unused = sorted((v for s, v in value.items() if s not in present), reverse=True)
    activated_now = min(left, max(0, MAX_SUBSTATS - shown), len(unused))
    new_values = unused[:activated_now]
    present_values = [value.get(s, 0.0) for s in present]
    best_final = max([*present_values, *new_values], default=0.0)
    ceiling = current + sum(new_values) + (left - activated_now) * best_final
    if left > 0 and shown < MAX_SUBSTATS:
        assumptions.append(
            f"The piece shows only {shown} of its {MAX_SUBSTATS} substats; the others are locked "
            "and unknown, so the ceiling assumes they are the best stats it could have."
        )
    if left > 0:
        assumptions.append(
            "The ceiling is a best case (every remaining upgrade lands on the best stat at its top "
            "tier), not a forecast."
        )

    if maximum > 0 and current > maximum + 1e-9:
        problems.append("the score is above the theoretical maximum: check the piece's data")

    return Potential(
        status="modelled",
        max_level=max_level,
        upgrades_left=left,
        floor=current,
        ceiling=ceiling,
        theoretical_max=maximum,
        theoretical_max_now=maximum_now,
        pct_of_max_now_level=_pct(current, maximum_now),
        pct_of_max=_pct(current, maximum),
        pct_ceiling_of_max=_pct(ceiling, maximum),
        rules_confidence=rules.confidence,
        assumptions=tuple(assumptions),
        problems=tuple(problems),
    )
