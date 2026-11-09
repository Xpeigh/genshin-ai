"""Potential model: floor, best-case ceiling and percent of the theoretical maximum (docs/potential-spec.md).

Expected numbers are worked out by hand from the tiny tier table in ``scoring_snapshot`` (5-star
tiers: CRIT 0.02/0.03/0.04, CRIT DMG 0.04/0.06/0.08, ATK% 0.04/0.05/0.06, HP 100/200/300, EM 10/20;
4-star ATK% 0.03/0.04/0.05) and the weights CRIT DMG 1.0, ATK% 0.5, CRIT 0.25 (HP and EM weigh 0).
"""

from __future__ import annotations

import itertools

import pytest

from genshin_companion.scoring import ArtifactRules, score_artifact
from helpers import scoring_snapshot
from test_scoring_artifact import ATKP, CD, CR, EM, HP, piece, profile

RULES = ArtifactRules(
    max_level={1: 4, 2: 4, 3: 12, 4: 16, 5: 20},
    confidence="provisional",
    source="test rules",
    observed_at="2026-11-09",
    notes=(),
)
W = {CD: 1.0, ATKP: 0.5, CR: 0.25}


def _pot(rolls, **over):  # type: ignore[no-untyped-def]
    prof = over.pop("prof", profile(weights=W))
    rules = over.pop("rules", RULES)
    return score_artifact(piece(rolls, **over), prof, scoring_snapshot(), rules).potential


def test_a_piece_with_three_substats_must_activate_a_fourth_in_the_best_case() -> None:
    # +0 5-star, main stat EM; rolls: CRIT DMG tier 3 (1.0), ATK% tier 1 (0.04/0.06 x 0.5), HP tier 1 (weight 0)
    p = _pot([(CD, 5, 3), (ATKP, 5, 1), (HP, 5, 1)], level=0, main_stat=EM)
    current = 1.0 + 0.5 * (0.04 / 0.06)
    assert p.status == "modelled" and (p.max_level, p.upgrades_left) == (20, 5)
    assert p.floor == pytest.approx(current)
    # first upgrade activates the only unused eligible stat (CRIT, 0.25), the other four hit CRIT DMG (1.0)
    assert p.ceiling == pytest.approx(current + 0.25 + 4 * 1.0)
    # best piece: four initial substats CD 1.0, ATK% 0.5, CRIT 0.25, HP 0 = 1.75, plus 5 upgrades on CD
    assert p.theoretical_max == pytest.approx(1.75 + 5 * 1.0)
    assert p.theoretical_max_now == pytest.approx(1.75)  # at +0 only the four initial rolls exist
    assert p.pct_of_max_now_level == pytest.approx(current / 1.75)
    assert p.pct_of_max == pytest.approx(current / 6.75)
    assert p.pct_ceiling_of_max == pytest.approx((current + 4.25) / 6.75)
    assert any("locked" in a or "fourth" in a for a in p.assumptions)


def test_a_piece_with_four_substats_puts_every_remaining_upgrade_on_its_best_stat() -> None:
    p = _pot([(CD, 5, 3), (ATKP, 5, 2), (CR, 5, 1), (HP, 5, 1)], level=4, main_stat=EM)
    current = 1.0 + 0.5 * (0.05 / 0.06) + 0.25 * (0.02 / 0.04)
    assert p.upgrades_left == 4
    assert p.ceiling == pytest.approx(current + 4 * 1.0)
    assert p.theoretical_max_now == pytest.approx(1.75 + 1 * 1.0)  # one upgrade done
    assert p.pct_of_max_now_level == pytest.approx(current / 2.75)
    assert not any("locked" in a for a in p.assumptions)


def test_a_maxed_piece_has_nothing_left() -> None:
    p = _pot(
        [(CD, 5, 3), (ATKP, 5, 2), (CR, 5, 1), (HP, 5, 1)] + [(CD, 5, 1)] * 5,
        level=20,
        main_stat=EM,
    )
    assert p.upgrades_left == 0 and p.ceiling == pytest.approx(p.floor)
    assert p.pct_ceiling_of_max == pytest.approx(p.pct_of_max)
    assert p.theoretical_max_now == pytest.approx(p.theoretical_max)


def test_the_main_stat_is_never_a_candidate() -> None:
    # with CRIT DMG as the main stat, the best eligible stat is ATK% (0.5): the maximum shrinks
    p = _pot([(ATKP, 5, 3), (CR, 5, 3), (HP, 5, 3)], level=0, main_stat=CD)
    assert p.theoretical_max == pytest.approx(
        (0.5 + 0.25 + 0 + 0) + 5 * 0.5
    )  # ATK%, CRIT, HP, EM(0)
    assert p.ceiling is not None and p.ceiling > p.floor


def test_a_lower_rarity_scales_by_its_own_top_tier_and_starts_with_fewer_substats() -> None:
    # 4-star: only ATK% has 4-star tiers in the table. Top tier 0.05 / best five-star 0.06 = 5/6.
    prof = profile(weights={ATKP: 1.0})
    p = _pot([(ATKP, 4, 3)], level=0, rarity=4, main_stat=EM, prof=prof)
    v = 0.05 / 0.06
    assert (p.max_level, p.upgrades_left) == (16, 4)
    assert p.floor == pytest.approx(v)  # tier 3 is the top tier: exactly 5/6
    assert p.ceiling == pytest.approx(
        v + 4 * v
    )  # no other eligible stat exists, all four upgrades on ATK%
    assert p.theoretical_max == pytest.approx(v + 4 * v)


def test_a_rarity_without_a_known_max_level_is_not_modelled_and_says_why() -> None:
    rules = ArtifactRules(
        max_level={5: 20}, confidence="provisional", source="t", observed_at="2026-11-09", notes=()
    )
    p = _pot([(ATKP, 4, 3)], level=0, rarity=4, rules=rules)
    assert p.status == "not_modelled" and "4" in (p.reason or "")
    assert p.ceiling is None and p.pct_of_max is None


def test_no_rules_means_no_potential() -> None:
    s = score_artifact(piece([(CD, 5, 3)]), profile(weights=W), scoring_snapshot())
    assert s.potential.status == "not_modelled" and "rules" in (s.potential.reason or "")


def test_a_profile_with_no_weighted_stats_gives_no_percentages_and_no_division() -> None:
    p = _pot([(CD, 5, 3)], prof=profile(weights={}), level=0, main_stat=EM)
    assert p.theoretical_max == 0.0 and p.ceiling == 0.0
    assert p.pct_of_max is None and p.pct_of_max_now_level is None and p.pct_ceiling_of_max is None


def test_a_level_above_the_maximum_is_reported_not_trusted() -> None:
    p = _pot(
        [(CD, 5, 3)],
        level=20,
        main_stat=EM,
        rules=ArtifactRules(
            max_level={5: 16},
            confidence="provisional",
            source="t",
            observed_at="2026-11-09",
            notes=(),
        ),
    )
    assert p.upgrades_left == 0 and any("above" in a for a in p.problems)


def test_the_floor_is_the_current_score_and_the_ceiling_never_goes_below_it() -> None:
    rolls = [(CD, 5, 3), (ATKP, 5, 2), (CR, 5, 1)]
    for level in range(0, 21):
        s = score_artifact(
            piece(rolls, level=level, main_stat=EM), profile(weights=W), scoring_snapshot(), RULES
        )
        p = s.potential
        assert p.floor == pytest.approx(s.roll_score)
        assert p.ceiling is not None and p.ceiling >= p.floor - 1e-12
        assert p.pct_of_max is not None and 0.0 <= p.pct_of_max <= 1.0 + 1e-12


def test_more_remaining_upgrades_never_lower_the_ceiling() -> None:
    rolls = [(CD, 5, 3), (ATKP, 5, 2), (CR, 5, 1), (HP, 5, 1)]
    ceilings = [
        score_artifact(
            piece(rolls, level=lv, main_stat=EM), profile(weights=W), scoring_snapshot(), RULES
        ).potential.ceiling
        for lv in (20, 16, 12, 8, 4)
    ]
    assert ceilings == sorted(ceilings)  # type: ignore[type-var]


def test_raising_a_weight_never_lowers_the_maximum() -> None:
    low = _pot([(CD, 5, 3)], prof=profile(weights={CD: 1.0}), level=0, main_stat=EM)
    high = _pot([(CD, 5, 3)], prof=profile(weights={CD: 1.0, ATKP: 0.5}), level=0, main_stat=EM)
    assert high.theoretical_max is not None and low.theoretical_max is not None
    assert high.theoretical_max >= low.theoretical_max


def test_roll_order_never_changes_the_potential() -> None:
    rolls = [(CD, 5, 3), (ATKP, 5, 2), (CR, 5, 1), (HP, 5, 1)]
    seen = {
        _pot(list(p), level=4, main_stat=EM).model_dump_json()
        for p in itertools.permutations(rolls)
    }
    assert len(seen) == 1
