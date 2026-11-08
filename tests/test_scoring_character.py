from __future__ import annotations

import pytest

from genshin_companion.scoring import (
    ArtifactInput,
    ArtifactScore,
    RecommendedMainStat,
    RecommendedSet,
    ScoringProfile,
    score_artifact,
)
from genshin_companion.scoring.character import SLOT_ORDER, summarize_character
from helpers import scoring_snapshot

P = "FIGHT_PROP_"
CD, ATKP, EM = P + "CRITICAL_HURT", P + "ATTACK_PERCENT", P + "ELEMENT_MASTERY"
ID = {"cd_best": "500203", "cd_low": "500201", "atk_mid": "500302"}


def _profile() -> ScoringProfile:
    return ScoringProfile(
        character_id="1",
        character_name="Hero",
        kind="in-game",
        source="test",
        observed_at="2026-11-08",
        confidence="curated",
        weights={CD: 1.0, ATKP: 1.0},
        unscored={},
        main_stats={"sands": [RecommendedMainStat(stat=EM)], "goblet": [], "circlet": []},
        sets=(
            RecommendedSet(sets=("Good Set",)),
            RecommendedSet(sets=("Fine Set",), tier="alternative"),
        ),
    )


def _score(
    slot: str, rolls: list[str], *, main: str = EM, set_name: str | None = "Good Set"
) -> ArtifactScore:
    art = ArtifactInput(
        slot=slot, rarity=5, level=4, set_name=set_name, main_stat=main, roll_affix_ids=rolls
    )  # type: ignore[arg-type]
    return score_artifact(art, _profile(), scoring_snapshot())


def test_summary_adds_up_scores_and_finds_the_weakest_and_strongest_slot() -> None:
    scores = {
        "flower": _score("flower", [ID["cd_best"]]),  # 1.0
        "plume": _score("plume", [ID["cd_low"]]),  # 0.5
        "sands": _score("sands", [ID["cd_best"], ID["atk_mid"]]),  # 1 + 5/6
    }
    s = summarize_character(scores)  # type: ignore[arg-type]
    assert s.total_roll_score == pytest.approx(1.0 + 0.5 + 1.0 + 5 / 6)
    assert (s.weakest_slot, s.strongest_slot, s.pieces_scored) == ("plume", "sands", 3)
    assert s.missing_slots == ("goblet", "circlet")


def test_ties_resolve_to_the_first_slot_in_game_order() -> None:
    scores = {
        "circlet": _score("circlet", [ID["cd_best"]]),
        "flower": _score("flower", [ID["cd_best"]]),
    }
    s = summarize_character(scores)  # type: ignore[arg-type]
    assert (s.weakest_slot, s.strongest_slot) == ("flower", "flower")


def test_main_stat_misses_and_recommended_set_pieces_are_counted() -> None:
    scores = {
        "sands": _score("sands", [], main=EM, set_name="Good Set"),  # recommended, best set
        "goblet": _score(
            "goblet", [], main=ATKP, set_name="Fine Set"
        ),  # goblet list is empty -> unknown
        "circlet": _score("circlet", [], main=ATKP, set_name="Elsewhere"),  # unknown, other set
        "flower": _score("flower", [], main=P + "HP", set_name="Good Set"),  # fixed slot
    }
    s = summarize_character(scores)  # type: ignore[arg-type]
    assert s.recommended_set_pieces == 3  # Good Set x2 + Fine Set (an alternative set counts)
    assert s.main_stat_not_listed == ()  # nothing is positively NOT on a list here


def test_a_main_stat_not_on_the_list_is_flagged() -> None:
    sands = _score("sands", [], main=ATKP)  # the sands list holds only Elemental Mastery
    s = summarize_character({"sands": sands})
    assert s.main_stat_not_listed == ("sands",)


def test_an_empty_character_has_no_weakest_slot() -> None:
    s = summarize_character({})
    assert (s.weakest_slot, s.strongest_slot, s.pieces_scored, s.total_roll_score) == (
        None,
        None,
        0,
        0.0,
    )
    assert s.missing_slots == SLOT_ORDER


def test_a_one_bit_float_difference_is_still_a_tie() -> None:
    base = _score("flower", [ID["cd_best"]])
    scores = {
        "flower": base.model_copy(update={"roll_score": 1.1666666666666667}),
        "plume": base.model_copy(update={"roll_score": 1.1666666666666665}),
    }
    s = summarize_character(scores)  # type: ignore[arg-type]
    assert (s.weakest_slot, s.strongest_slot) == ("flower", "flower")
