"""Advice rules for the `recommend` command. Pure: profile + scored pieces + equipped weapon in, ordered
advice out. Numbers come from scoring; nothing is invented here."""

from __future__ import annotations

import pytest

from genshin_companion.builds.profiles import CharacterProfile, load_profiles
from genshin_companion.builds.recommend import Advice, PieceView, advise
from genshin_companion.builds.scoring_profile import to_scoring_profile
from genshin_companion.scoring import ArtifactInput, score_artifact
from helpers import scoring_snapshot
from test_builds_profiles import GOOD, WEAPON_BLOCK
from test_scoring_potential import RULES

P = "FIGHT_PROP_"
ATKP, HPP, HP, DEFP = P + "ATTACK_PERCENT", P + "HP_PERCENT", P + "HP", P + "DEFENSE_PERCENT"
# affix ids in scoring_snapshot: ATK% 5-star tiers 500301..500303 (0.04, 0.05, 0.06); HP 500401..500403
ATK_LOW, ATK_HIGH, HP_ROLL = "500301", "500303", "500402"


def _profile(text: str = GOOD) -> CharacterProfile:
    (p,) = load_profiles(text.replace(', "Test Set Two"', ""))
    return p


def _view(
    slot: str,
    *,
    main: str = ATKP,
    set_name: str | None = "Test Set",
    rolls: list[str] | None = None,
    level: int = 20,
    rules: object = None,
) -> PieceView:
    # the profile's sands list is ATK%, goblet HP, circlet ATK% (+ HP at C6)
    art = ArtifactInput(
        slot=slot,
        rarity=5,
        level=level,
        set_name=set_name,
        main_stat=main,
        roll_affix_ids=[ATK_HIGH] if rolls is None else rolls,
    )  # type: ignore[arg-type]
    score = score_artifact(art, to_scoring_profile(_profile()), scoring_snapshot(), rules)  # type: ignore[arg-type]
    return PieceView(
        slot=slot, level=level, rarity=5, main_stat=main, set_name=set_name, score=score
    )  # type: ignore[arg-type]


def _full(**over: PieceView) -> list[PieceView]:
    base = {
        "flower": _view("flower", main=HP),
        "plume": _view("plume", main=P + "ATTACK"),
        "sands": _view("sands", main=ATKP),
        "goblet": _view("goblet", main=HP),
        "circlet": _view("circlet", main=ATKP),
    }
    base.update(over)
    return list(base.values())


def _kinds(advice: list[Advice]) -> list[tuple[str, str | None]]:
    return [(a.kind, a.slot) for a in advice]


def test_a_complete_well_built_character_only_gets_the_weakest_rolls_note() -> None:
    advice = advise(_profile(), _full(), weapon_name=None)
    assert [a.kind for a in advice] == ["rolls"]


def test_missing_slots_come_first_in_game_order() -> None:
    pieces = [v for v in _full() if v.slot not in ("plume", "circlet")]
    advice = advise(_profile(), pieces, weapon_name=None)
    assert _kinds(advice)[:2] == [("missing", "plume"), ("missing", "circlet")]
    assert advice[0].priority == advice[1].priority == 1


def test_a_main_stat_that_is_not_listed_asks_for_a_replacement_with_the_recommended_stats() -> None:
    bad_goblet = _view("goblet", main=DEFP)
    advice = advise(_profile(), _full(goblet=bad_goblet), weapon_name=None)
    a = next(x for x in advice if x.kind == "main_stat")
    assert a.slot == "goblet" and a.main_stat == DEFP and a.priority == 2
    assert a.recommended == (HP,)  # the unconditional recommendation(s) for that slot


def test_a_conditional_listing_is_not_a_replacement_request() -> None:
    circlet_with_hp = _view("circlet", main=HP)  # HP is only recommended "at C6" for the circlet
    advice = advise(_profile(), _full(circlet=circlet_with_hp), weapon_name=None)
    assert all(a.kind != "main_stat" for a in advice)


def test_fixed_slots_and_unknown_recommendations_never_ask_for_a_new_main_stat() -> None:
    text = GOOD.replace(
        'goblet = ["FIGHT_PROP_HP"]\n', ""
    )  # the profile records nothing for the goblet
    prof = _profile(text)
    art = ArtifactInput(
        slot="goblet",
        rarity=5,
        level=20,
        set_name="Test Set",
        main_stat=DEFP,
        roll_affix_ids=[ATK_HIGH],
    )
    score = score_artifact(art, to_scoring_profile(prof), scoring_snapshot())
    assert score.main_stat_fit.status == "unknown"
    goblet = PieceView(
        slot="goblet", level=20, rarity=5, main_stat=DEFP, set_name="Test Set", score=score
    )
    pieces = [v for v in _full() if v.slot != "goblet"] + [goblet]
    assert all(a.kind != "main_stat" for a in advise(prof, pieces, weapon_name=None))


def test_a_piece_from_an_unrecommended_set_is_flagged_with_the_recommended_sets_best_first() -> (
    None
):
    advice = advise(_profile(), _full(sands=_view("sands", set_name="Other Set")), weapon_name=None)
    a = next(x for x in advice if x.kind == "set")
    assert (a.slot, a.set_name, a.priority) == ("sands", "Other Set", 3)
    assert a.recommended == ("Test Set",)


def test_no_set_advice_when_the_profile_records_no_sets() -> None:
    text = GOOD.replace(
        '[[profile.recommended_sets]]\nsets = ["Test Set"]\nusage_percent = 70.1\n', ""
    )
    text = text.replace(
        '[[profile.recommended_sets]]\nsets = ["Test Set", "Test Set Two"]\ntier = "alternative"\ncondition = "if nobody else uses the first set"\n',
        "",
    )
    advice = advise(
        _profile(text), _full(sands=_view("sands", set_name="Other Set")), weapon_name=None
    )
    assert all(a.kind != "set" for a in advice)


def test_the_weakest_rolls_note_uses_the_average_per_roll_not_the_total() -> None:
    # a piece with one great roll beats a piece with three mediocre ones on average, even though the
    # three-roll piece has the larger total: an un-upgraded piece is not punished for having few rolls
    great_few = _view("flower", main=HP, rolls=[ATK_HIGH], level=0)
    mediocre_many = _view("plume", main=P + "ATTACK", rolls=[ATK_LOW, ATK_LOW, ATK_LOW], level=20)
    advice = advise(_profile(), _full(flower=great_few, plume=mediocre_many), weapon_name=None)
    a = next(x for x in advice if x.kind == "rolls")
    assert a.slot == "plume" and a.level == 20
    assert a.value == pytest.approx(0.04 / 0.06)  # the average value of those rolls


def test_pieces_already_flagged_for_main_stat_or_set_are_not_named_as_weakest_rolls() -> None:
    bad = _view(
        "goblet", main=DEFP, rolls=[ATK_LOW]
    )  # flagged: main stat, and it also has the worst rolls
    advice = advise(_profile(), _full(goblet=bad), weapon_name=None)
    rolls = [a for a in advice if a.kind == "rolls"]
    assert all(a.slot != "goblet" for a in rolls)


def test_pieces_with_no_rolls_are_never_the_weakest() -> None:
    empty = _view(
        "plume", main=P + "ATTACK", rolls=[HP_ROLL], level=0
    )  # only a non-favoured roll: average 0.0
    assert any(a.kind == "rolls" for a in advise(_profile(), [empty], weapon_name=None))
    nothing = _view("flower", main=HP, rolls=[], level=0)  # no rolls at all
    assert nothing.score.total_rolls == 0
    assert all(a.kind != "rolls" for a in advise(_profile(), [nothing], weapon_name=None))


def test_weapon_advice_only_when_the_equipped_weapon_is_not_recommended() -> None:
    p = _profile(GOOD + WEAPON_BLOCK)
    assert all(a.kind != "weapon" for a in advise(p, _full(), weapon_name="Test Sword"))
    other = next(a for a in advise(p, _full(), weapon_name="Rusty Blade") if a.kind == "weapon")
    assert other.recommended == ("Test Sword",) and other.priority == 6
    assert all(
        a.kind != "weapon" for a in advise(_profile(), _full(), weapon_name="Rusty Blade")
    )  # no list recorded
    assert all(
        a.kind != "weapon" for a in advise(p, _full(), weapon_name=None)
    )  # unknown weapon: stay silent


def test_advice_is_sorted_by_priority_then_slot_order_and_is_deterministic() -> None:
    pieces = [
        v
        for v in _full(
            goblet=_view("goblet", main=DEFP), sands=_view("sands", set_name="Other Set")
        )
        if v.slot != "flower"
    ]
    advice = advise(_profile(GOOD + WEAPON_BLOCK), pieces, weapon_name="Rusty Blade")
    assert [a.priority for a in advice] == sorted(a.priority for a in advice)
    assert _kinds(advice)[:3] == [("missing", "flower"), ("main_stat", "goblet"), ("set", "sands")]
    assert advice == advise(_profile(GOOD + WEAPON_BLOCK), pieces, weapon_name="Rusty Blade")


# --- level-up advice (potential model) --------------------------------------------------------


def test_level_up_names_the_two_best_rolled_pieces_that_can_still_be_upgraded() -> None:
    cr, em, cd_low = "500103", "500502", "500201"  # three substats the profile does not weigh
    four = [cr, em, cd_low]
    pieces = _full(
        flower=_view("flower", main=HP, rolls=[ATK_HIGH, *four], level=8, rules=RULES),  # avg 0.25
        plume=_view(
            "plume", main=P + "ATTACK", rolls=[ATK_LOW, *four], level=8, rules=RULES
        ),  # 0.17
        circlet=_view(
            "circlet", main=HP, rolls=[ATK_HIGH, *four], level=4, rules=RULES
        ),  # avg 0.25
    )
    advice = advise(_profile(), pieces, weapon_name=None)
    ups = [a for a in advice if a.kind == "level_up"]
    assert [a.slot for a in ups] == ["flower", "circlet"]  # best average first, ties by slot order
    assert ups[0].priority == 5 and ups[0].level == 8
    assert ups[0].value == pytest.approx(0.25)
    assert ups[0].ceiling == pytest.approx(
        1.0 + 3 * 1.0
    )  # 3 upgrades left, all on ATK% (weight 1.0)
    assert ups[0].pct_ceiling is not None


def test_nothing_is_levelled_up_without_rules_or_for_maxed_or_flagged_pieces() -> None:
    assert all(
        a.kind != "level_up" for a in advise(_profile(), _full(), weapon_name=None)
    )  # no rules
    maxed = _full(flower=_view("flower", main=HP, level=20, rules=RULES))
    assert all(a.slot != "flower" for a in advise(_profile(), maxed, None) if a.kind == "level_up")
    flagged = _full(
        goblet=_view("goblet", main=DEFP, level=4, rules=RULES)
    )  # main stat off the list
    assert all(
        a.slot != "goblet" for a in advise(_profile(), flagged, None) if a.kind == "level_up"
    )


def test_a_piece_without_a_useful_roll_is_not_worth_levelling() -> None:
    dud = _view(
        "plume", main=P + "ATTACK", rolls=[HP_ROLL], level=4, rules=RULES
    )  # only an unweighted roll
    advice = advise(_profile(), _full(plume=dud), weapon_name=None)
    assert all(a.slot != "plume" for a in advice if a.kind == "level_up")
