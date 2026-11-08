"""Formula tests for piece scoring. Expected numbers are worked out by hand from the made-up tier
table in ``scoring_snapshot`` (round numbers), so they test the arithmetic, not game data."""

from __future__ import annotations

import itertools

import pytest

from genshin_companion.scoring import (
    ArtifactInput,
    RecommendedMainStat,
    RecommendedSet,
    ScoringProfile,
    score_artifact,
)
from helpers import scoring_snapshot

P = "FIGHT_PROP_"
CR, CD, ATKP, HP, EM = (
    P + "CRITICAL",
    P + "CRITICAL_HURT",
    P + "ATTACK_PERCENT",
    P + "HP",
    P + "ELEMENT_MASTERY",
)

# affix ids in scoring_snapshot: (stat, rarity, position) -> id; values and best-5-star maxima:
#   CRIT       5*: 0.02 0.03 0.04            (best 0.04)
#   CRIT DMG   5*: 0.04 0.06 0.08            (best 0.08)
#   ATK%       5*: 0.04 0.05 0.06 (best 0.06); 4*: 0.03 0.04 0.05
#   HP         5*: 100 200 300               (best 300)
#   EM         5*: 10 20                     (best 20)
ID = {
    (CR, 5, 1): "500101", (CR, 5, 2): "500102", (CR, 5, 3): "500103",
    (CD, 5, 1): "500201", (CD, 5, 2): "500202", (CD, 5, 3): "500203",
    (ATKP, 5, 1): "500301", (ATKP, 5, 2): "500302", (ATKP, 5, 3): "500303",
    (ATKP, 4, 1): "400301", (ATKP, 4, 2): "400302", (ATKP, 4, 3): "400303",
    (HP, 5, 1): "500401", (HP, 5, 2): "500402", (HP, 5, 3): "500403",
    (EM, 5, 1): "500501", (EM, 5, 2): "500502",
}  # fmt: skip


def profile(**over: object) -> ScoringProfile:
    base: dict[str, object] = {
        "character_id": "10000002",
        "character_name": "Test Hero",
        "kind": "in-game",
        "source": "test profile",
        "observed_at": "2026-11-08",
        "confidence": "curated",
        "weights": {CD: 1.0, ATKP: 1.0},
        "unscored": {},
        "main_stats": {},
        "sets": (),
        "weights_note": None,
    }
    base.update(over)
    return ScoringProfile.model_validate(base)


def piece(rolls: list[tuple[str, int, int]], **over: object) -> ArtifactInput:
    base: dict[str, object] = {
        "slot": "sands",
        "rarity": 5,
        "level": 4,
        "set_name": "Test Set",
        "main_stat": EM,
        "roll_affix_ids": [ID[r] for r in rolls],
    }
    base.update(over)
    return ArtifactInput.model_validate(base)


def test_roll_score_is_weight_times_tier_over_best_five_star_tier() -> None:
    # CRIT DMG tier 3 = 0.08 / best 0.08 = 1.0 ; ATK% tier 2 = 0.05 / 0.06 = 5/6 ; HP has weight 0
    art = piece([(CD, 5, 3), (ATKP, 5, 2), (HP, 5, 2)])
    s = score_artifact(art, profile(), scoring_snapshot())
    assert s.roll_score == pytest.approx(1.0 + 5 / 6)
    assert (s.total_rolls, s.useful_rolls) == (3, 2)
    assert s.average_per_roll == pytest.approx((1.0 + 5 / 6) / 3)
    assert s.problems == ()


def test_weights_scale_each_roll() -> None:
    art = piece([(CD, 5, 3), (ATKP, 5, 2)])
    s = score_artifact(art, profile(weights={CD: 0.5, ATKP: 0.75}), scoring_snapshot())
    assert s.roll_score == pytest.approx(0.5 * 1.0 + 0.75 * 5 / 6)


def test_a_lower_rarity_roll_is_worth_less_than_the_same_tier_at_five_stars() -> None:
    # 4-star ATK% tier 3 = 0.05, still measured against the best FIVE-star roll 0.06
    four = piece([(ATKP, 4, 3)], rarity=4)
    five = piece([(ATKP, 5, 3)])
    assert score_artifact(four, profile(), scoring_snapshot()).roll_score == pytest.approx(5 / 6)
    assert score_artifact(five, profile(), scoring_snapshot()).roll_score == pytest.approx(1.0)


def test_two_rolls_on_one_stat_add_up_and_are_listed_once() -> None:
    art = piece([(ATKP, 5, 1), (ATKP, 5, 3), (CD, 5, 1)])
    s = score_artifact(art, profile(), scoring_snapshot())
    assert s.roll_score == pytest.approx(0.04 / 0.06 + 0.06 / 0.06 + 0.04 / 0.08)
    atk = next(b for b in s.stats if b.stat == ATKP)
    assert atk.rolls == 2 and atk.values == (0.04, 0.06)
    assert atk.contribution == pytest.approx(0.04 / 0.06 + 1.0)


def test_no_rolls_scores_zero_without_dividing_by_zero() -> None:
    s = score_artifact(piece([], level=0), profile(), scoring_snapshot())
    assert (s.roll_score, s.total_rolls, s.useful_rolls, s.average_per_roll) == (0.0, 0, 0, 0.0)


def test_crit_value_is_twice_crit_rate_plus_crit_dmg_in_percent_points() -> None:
    # CRIT Rate 0.04 -> 4 points, x2 = 8 ; CRIT DMG 0.08 -> 8 points ; ATK% is ignored
    art = piece([(CR, 5, 3), (CD, 5, 3), (ATKP, 5, 1)])
    s = score_artifact(art, profile(weights={}), scoring_snapshot())
    assert s.crit_value == pytest.approx(2 * 4.0 + 8.0)
    assert s.roll_score == 0.0  # crit value is reported even when the profile does not favour crit


def test_conditional_stats_are_not_scored_but_listed_with_their_condition() -> None:
    art = piece([(CD, 5, 1), (ATKP, 5, 3)])
    s = score_artifact(
        art,
        profile(weights={ATKP: 1.0}, unscored={CD: "only with Favonius Lance"}),
        scoring_snapshot(),
    )
    assert s.roll_score == pytest.approx(1.0)
    assert [(n.stat, n.condition, n.rolls) for n in s.not_scored] == [
        (CD, "only with Favonius Lance", 1)
    ]


def test_a_roll_on_the_main_stat_is_a_problem_and_never_scored() -> None:
    art = piece([(ATKP, 5, 3), (CD, 5, 3)], main_stat=ATKP)
    s = score_artifact(art, profile(), scoring_snapshot())
    assert s.roll_score == pytest.approx(1.0)  # only the CRIT DMG roll counts
    assert any("main stat" in p for p in s.problems)


def test_unknown_roll_id_and_wrong_rarity_are_problems_not_scores() -> None:
    art = piece([(CD, 5, 3)], roll_affix_ids=["999999", ID[(CD, 5, 3)]])
    s = score_artifact(art, profile(), scoring_snapshot())
    assert s.roll_score == pytest.approx(1.0) and any("999999" in p for p in s.problems)
    wrong = piece([(ATKP, 4, 3)], rarity=5)  # a 4-star roll on a 5-star piece
    s2 = score_artifact(wrong, profile(), scoring_snapshot())
    assert s2.roll_score == 0.0 and any("rarity" in p for p in s2.problems)


@pytest.mark.parametrize(
    ("slot", "main_stats", "expected"),
    [
        ("flower", {}, ("fixed", None, None)),
        ("plume", {}, ("fixed", None, None)),
        (
            "sands",
            {"sands": [RecommendedMainStat(stat=EM, usage_percent=89.7)]},
            ("recommended", 89.7, None),
        ),
        ("sands", {"sands": [RecommendedMainStat(stat=EM)]}, ("recommended", None, None)),
        (
            "sands",
            {"sands": [RecommendedMainStat(stat=ATKP, usage_percent=10.0)]},
            ("not_listed", None, None),
        ),
        (
            "sands",
            {"sands": [RecommendedMainStat(stat=EM, usage_percent=3.0, condition="only at C6")]},
            ("conditional", 3.0, "only at C6"),
        ),
        ("sands", {}, ("unknown", None, None)),  # the profile records nothing for this slot
    ],
)
def test_main_stat_fit(
    slot: str, main_stats: dict[str, list[RecommendedMainStat]], expected: tuple
) -> None:  # type: ignore[type-arg]
    s = score_artifact(
        piece([], slot=slot, level=0), profile(main_stats=main_stats), scoring_snapshot()
    )
    assert (
        s.main_stat_fit.status,
        s.main_stat_fit.usage_percent,
        s.main_stat_fit.condition,
    ) == expected


def test_a_conditional_listing_loses_to_an_unconditional_one() -> None:
    both = [
        RecommendedMainStat(stat=EM, usage_percent=3.0, condition="only at C6"),
        RecommendedMainStat(stat=EM, usage_percent=50.0),
    ]
    s = score_artifact(piece([], level=0), profile(main_stats={"sands": both}), scoring_snapshot())
    assert (s.main_stat_fit.status, s.main_stat_fit.usage_percent) == ("recommended", 50.0)


def test_set_fit_best_alternative_pair_and_other() -> None:
    sets = (
        RecommendedSet(sets=("Test Set",), tier="alternative", usage_percent=20.0),
        RecommendedSet(sets=("Test Set", "Other Set"), tier="best", usage_percent=30.0),
        RecommendedSet(sets=("Third Set",), tier="alternative"),
    )
    snap = scoring_snapshot()
    best = score_artifact(piece([], level=0), profile(sets=sets), snap).set_fit
    assert (best.status, best.usage_percent) == ("best", 30.0)  # best beats alternative
    alt = score_artifact(piece([], level=0, set_name="Third Set"), profile(sets=sets), snap).set_fit
    assert (alt.status, alt.usage_percent) == ("alternative", None)
    other = score_artifact(
        piece([], level=0, set_name="Unlisted"), profile(sets=sets), snap
    ).set_fit
    assert other.status == "other"
    none = score_artifact(piece([], level=0, set_name=None), profile(sets=sets), snap).set_fit
    assert none.status == "other"


@pytest.mark.parametrize(
    ("profile_conf", "data_conf", "expected"),
    [
        ("curated", "curated", "curated"),
        ("provisional", "curated", "provisional"),
        ("curated", "provisional", "provisional"),
        ("provisional", "provisional", "provisional"),
    ],
)
def test_confidence_is_the_weakest_of_profile_and_data(
    profile_conf: str, data_conf: str, expected: str
) -> None:
    snap = scoring_snapshot(substat_confidence=data_conf)
    s = score_artifact(piece([(CD, 5, 3)]), profile(confidence=profile_conf), snap)
    assert s.provenance.confidence == expected
    assert s.provenance.data_version == "7.2"
    assert (s.provenance.profile_kind, s.provenance.profile_source) == ("in-game", "test profile")
    assert s.provenance.profile_observed_at == "2026-11-08"


def test_the_weights_note_is_carried_into_the_provenance() -> None:
    p = profile(kind="guide", weights_note="tier weights are a convention")
    s = score_artifact(piece([]), p, scoring_snapshot())
    assert s.provenance.weights_note == "tier weights are a convention"


def test_roll_order_never_changes_the_result() -> None:
    rolls = [(CD, 5, 3), (ATKP, 5, 2), (HP, 5, 1), (CR, 5, 2), (EM, 5, 1)]
    results = {
        score_artifact(
            piece(list(perm)), profile(weights={CD: 1.0, ATKP: 0.5, CR: 0.25}), scoring_snapshot()
        ).model_dump_json()
        for perm in itertools.permutations(rolls)
    }
    assert len(results) == 1  # identical, including the (sorted) breakdown order


def test_breakdown_is_sorted_by_stat_id() -> None:
    s = score_artifact(piece([(HP, 5, 1), (CD, 5, 1), (ATKP, 5, 1)]), profile(), scoring_snapshot())
    assert [b.stat for b in s.stats] == sorted(b.stat for b in s.stats)


@pytest.mark.parametrize(
    "weights", [{}, {CD: 1.0}, {CD: 1.0, ATKP: 1.0, HP: 1.0, CR: 1.0, EM: 1.0}]
)
def test_the_score_is_never_negative_or_above_the_roll_count(weights: dict[str, float]) -> None:
    art = piece([(CD, 5, 3), (ATKP, 5, 3), (HP, 5, 3), (CR, 5, 3), (EM, 5, 2)])
    s = score_artifact(art, profile(weights=weights), scoring_snapshot())
    assert 0.0 <= s.roll_score <= s.total_rolls


def test_score_artifact_does_not_mutate_its_inputs() -> None:
    art, prof, snap = piece([(CD, 5, 3)]), profile(), scoring_snapshot()
    before = (art.model_dump_json(), prof.model_dump_json(), snap.model_dump_json())
    score_artifact(art, prof, snap)
    assert (art.model_dump_json(), prof.model_dump_json(), snap.model_dump_json()) == before


# --- review hardening (2026-11-08) ------------------------------------------------------------


def test_total_rolls_counts_only_valid_rolls() -> None:
    art = piece([(CD, 5, 3)], roll_affix_ids=["999999", ID[(CD, 5, 3)]])
    s = score_artifact(art, profile(), scoring_snapshot())
    assert (s.total_rolls, s.useful_rolls, s.average_per_roll) == (1, 1, 1.0)


def test_a_five_star_roll_on_a_four_star_piece_is_rejected_too() -> None:
    s = score_artifact(piece([(ATKP, 5, 3)], rarity=4), profile(), scoring_snapshot())
    assert s.roll_score == 0.0 and s.total_rolls == 0 and any("rarity" in p for p in s.problems)


def test_a_stat_with_no_five_star_reference_roll_is_a_problem_not_a_crash() -> None:
    snap = scoring_snapshot()
    only_four_star = snap.model_copy(
        update={
            "substat_tiers": [
                t for t in snap.substat_tiers if not (t.stat == ATKP and t.rarity == 5)
            ]
        }
    )
    s = score_artifact(piece([(ATKP, 4, 3)], rarity=4), profile(), only_four_star)
    assert s.roll_score == 0.0 and s.total_rolls == 0
    assert any("five-star reference" in p for p in s.problems)


def test_values_inside_one_stat_are_ascending_whatever_the_roll_order() -> None:
    a = score_artifact(piece([(ATKP, 5, 3), (ATKP, 5, 1)]), profile(), scoring_snapshot())
    b = score_artifact(piece([(ATKP, 5, 1), (ATKP, 5, 3)]), profile(), scoring_snapshot())
    assert a.stats[0].values == b.stats[0].values == (0.04, 0.06)
    assert a == b


def test_sums_do_not_depend_on_roll_order_to_the_last_bit() -> None:
    rolls = [(CR, 5, 1)] * 3 + [(CR, 5, 2)] * 3 + [(CR, 5, 3)] * 2 + [(CD, 5, 1), (CD, 5, 2)]
    seen = set()
    for perm in set(itertools.permutations(rolls)):
        s = score_artifact(
            piece(list(perm)), profile(weights={CR: 1.0, CD: 0.3}), scoring_snapshot()
        )
        seen.add((s.roll_score, s.crit_value, s.average_per_roll))
    assert len(seen) == 1


def test_set_fit_second_member_of_a_pair_and_the_unconditional_listing_wins() -> None:
    pair = (RecommendedSet(sets=("Test Set", "Other Set"), tier="best", usage_percent=30.0),)
    assert (
        score_artifact(
            piece([], set_name="Other Set"), profile(sets=pair), scoring_snapshot()
        ).set_fit.status
        == "best"
    )
    sets = (
        RecommendedSet(
            sets=("Test Set",), tier="best", usage_percent=10.0, condition="only with X"
        ),
        RecommendedSet(sets=("Test Set",), tier="alternative", usage_percent=50.0),
    )
    fit = score_artifact(piece([]), profile(sets=sets), scoring_snapshot()).set_fit
    assert (fit.status, fit.usage_percent, fit.condition) == ("alternative", 50.0, None)
    only_conditional = score_artifact(piece([]), profile(sets=sets[:1]), scoring_snapshot()).set_fit
    assert (only_conditional.status, only_conditional.condition) == ("best", "only with X")


def test_between_two_alternatives_the_first_listed_is_used() -> None:
    sets = (
        RecommendedSet(sets=("Test Set",), tier="alternative", usage_percent=5.0),
        RecommendedSet(sets=("Test Set",), tier="alternative", usage_percent=9.0),
    )
    assert (
        score_artifact(piece([]), profile(sets=sets), scoring_snapshot()).set_fit.usage_percent
        == 5.0
    )


@pytest.mark.parametrize(
    ("profile_conf", "data_conf", "expected"),
    [
        ("verified", "verified", "verified"),
        ("verified", "curated", "curated"),
        ("curated", "verified", "curated"),
    ],
)
def test_confidence_ranking_includes_verified(
    profile_conf: str, data_conf: str, expected: str
) -> None:
    snap = scoring_snapshot(substat_confidence=data_conf)
    snap = snap.model_copy(update={"confidence": {**snap.confidence, "artifact_sets": data_conf}})  # type: ignore[dict-item]
    assert (
        score_artifact(piece([]), profile(confidence=profile_conf), snap).provenance.confidence
        == expected
    )


def test_a_missing_data_confidence_means_provisional_not_verified() -> None:
    snap = scoring_snapshot()
    snap = snap.model_copy(update={"confidence": {}})
    assert (
        score_artifact(piece([]), profile(confidence="verified"), snap).provenance.confidence
        == "provisional"
    )


def test_the_set_data_confidence_counts_when_the_piece_has_a_set() -> None:
    snap = scoring_snapshot()
    snap = snap.model_copy(
        update={"confidence": {**snap.confidence, "artifact_sets": "provisional"}}
    )  # type: ignore[dict-item]
    assert (
        score_artifact(piece([], set_name="Test Set"), profile(), snap).provenance.confidence
        == "provisional"
    )
    assert (
        score_artifact(piece([], set_name=None), profile(), snap).provenance.confidence == "curated"
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"weights": {CD: 5.0}},
        {"weights": {CD: -0.1}},
        {"weights": {CD: float("nan")}},
        {"weights": {CD: float("inf")}},
        {"weights": {CD: 1.0}, "unscored": {CD: "only with X"}},  # scored AND not scored
    ],
)
def test_a_scoring_profile_rejects_weights_that_break_the_score_bounds(
    bad: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        profile(**bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"roll_affix_ids": ["12345" + chr(27)]},
        {"roll_affix_ids": ["not-a-number"]},
        {"roll_affix_ids": ["500101"] * 17},
        {"main_stat": "BOGUS"},
    ],
)
def test_an_artifact_input_rejects_untrusted_shapes(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        piece([], **bad)


def test_the_order_of_weights_and_listings_in_a_profile_never_changes_the_result() -> None:
    rolls = [(CD, 5, 3), (ATKP, 5, 2), (HP, 5, 1), (CR, 5, 2)]
    weights = [(CD, 1.0), (ATKP, 0.5), (HP, 0.25)]
    unscored = [(CR, "only with X")]
    results = set()
    for w_perm in itertools.permutations(weights):
        for u_perm in itertools.permutations(unscored):
            prof = profile(weights=dict(w_perm), unscored=dict(u_perm))
            results.add(score_artifact(piece(rolls), prof, scoring_snapshot()).model_dump_json())
    assert len(results) == 1
