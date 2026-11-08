from __future__ import annotations

from genshin_companion.builds.profiles import CharacterProfile, load_profiles
from genshin_companion.builds.scoring_profile import select_profile, to_scoring_profile
from test_builds_profiles import GOOD, HEADER, WEIGHTS

P = "FIGHT_PROP_"


def _profile(text: str) -> CharacterProfile:
    (p,) = load_profiles(text)
    return p


def _tiers(*tiers: str, kind: str = "guide") -> CharacterProfile:
    body = "substat_tiers = [\n" + "".join(f"    [{t}],\n" for t in tiers) + "]\n"
    text = (
        HEADER.replace('confidence = "provisional"', f'confidence = "provisional"\nkind = "{kind}"')
        + body
    )
    return _profile(text)


def test_a_single_in_game_tier_gives_every_favoured_stat_weight_one() -> None:
    p = _tiers(
        f'"{P}CRITICAL_HURT", "{P}CRITICAL", "{P}ATTACK_PERCENT", "{P}ELEMENT_MASTERY"',
        kind="in-game",
    )
    sp = to_scoring_profile(p)
    assert sp.weights == {
        P + "CRITICAL_HURT": 1.0,
        P + "CRITICAL": 1.0,
        P + "ATTACK_PERCENT": 1.0,
        P + "ELEMENT_MASTERY": 1.0,
    }
    assert sp.unscored == {} and sp.weights_note is None and sp.kind == "in-game"


def test_guide_tiers_step_down_by_a_quarter_with_ties_sharing_a_weight() -> None:
    p = _tiers(
        f'"{P}HP_PERCENT"',
        f'"{P}CHARGE_EFFICIENCY", "{P}CRITICAL"',
        f'"{P}HP"',
        f'"{P}ELEMENT_MASTERY"',
    )
    sp = to_scoring_profile(p)
    assert sp.weights == {
        P + "HP_PERCENT": 1.0,
        P + "CHARGE_EFFICIENCY": 0.75,
        P + "CRITICAL": 0.75,
        P + "HP": 0.5,
        P + "ELEMENT_MASTERY": 0.25,
    }
    assert sp.weights_note and "convention" in sp.weights_note


def test_weights_never_fall_below_the_floor() -> None:
    stats = ["HP", "ATTACK", "DEFENSE", "CRITICAL", "CRITICAL_HURT", "ELEMENT_MASTERY"]
    p = _tiers(*[f'"{P}{s}"' for s in stats])
    sp = to_scoring_profile(p)
    assert [sp.weights[P + s] for s in stats] == [1.0, 0.75, 0.5, 0.25, 0.25, 0.25]


def test_conditional_stats_are_unscored_but_keep_their_rank_position() -> None:
    cond = f'{{ stat = "{P}CHARGE_EFFICIENCY", condition = "only up to the ER target" }}'
    p = _tiers(
        cond,
        f'"{P}ELEMENT_MASTERY"',
        f'{{ stat = "{P}CRITICAL", condition = "only with Favonius Lance" }}',
    )
    sp = to_scoring_profile(p)
    assert sp.weights == {
        P + "ELEMENT_MASTERY": 0.75
    }  # it stays second even though tier one is unscored
    assert sp.unscored == {
        P + "CHARGE_EFFICIENCY": "only up to the ER target",
        P + "CRITICAL": "only with Favonius Lance",
    }


def test_flat_weights_pass_through_unchanged() -> None:
    sp = to_scoring_profile(_profile(WEIGHTS))
    assert sp.weights == {P + "HP": 0.5, P + "ATTACK_PERCENT": 1.0}
    assert sp.weights_note is None


def test_main_stats_sets_and_provenance_are_carried_over() -> None:
    sp = to_scoring_profile(_profile(GOOD))
    assert [(m.stat, m.usage_percent, m.condition) for m in sp.main_stats["circlet"]] == [
        (P + "ATTACK_PERCENT", None, None),
        (P + "HP", None, "only at C6"),
    ]
    assert "flower" not in sp.main_stats and "plume" not in sp.main_stats
    assert [(s.sets, s.tier, s.usage_percent, s.condition) for s in sp.sets] == [
        (("Test Set",), "best", 70.1, None),
        (("Test Set", "Test Set Two"), "alternative", None, "if nobody else uses the first set"),
    ]
    assert (sp.character_id, sp.character_name) == ("10000002", "Test Hero")
    assert (sp.kind, sp.observed_at, sp.confidence) == ("in-game", "2026-11-08", "provisional")
    assert "recently active players" in sp.source


def test_select_profile_prefers_in_game_over_guide() -> None:
    game = _profile(GOOD)
    guide = _profile(
        GOOD.replace('confidence = "provisional"', 'confidence = "provisional"\nkind = "guide"', 1)
    )
    assert select_profile([guide, game], "10000002") is game
    assert select_profile([guide], "10000002") is guide
    assert select_profile([game], "99999999") is None


def test_select_profile_matches_a_variant_id_for_the_base_avatar() -> None:
    # the Traveler is avatar 10000007 in a roster while a profile may be keyed per element
    p = _profile(GOOD.replace('character_id = "10000002"', 'character_id = "10000007-705"'))
    assert select_profile([p], "10000007") is p
    assert select_profile([p], "100000071") is None  # a prefix of the digits is not a match


# --- review hardening (2026-11-08) ------------------------------------------------------------


def test_an_in_game_profile_is_an_unordered_set_whatever_its_tiers() -> None:
    p = _tiers(f'"{P}CRITICAL_HURT"', f'"{P}CRITICAL"', kind="in-game")
    assert to_scoring_profile(p).weights == {P + "CRITICAL_HURT": 1.0, P + "CRITICAL": 1.0}


def test_every_guide_result_is_labelled_as_using_conventional_weights() -> None:
    one_tier = to_scoring_profile(_tiers(f'"{P}CRITICAL"', kind="guide"))
    assert one_tier.weights_note and "convention" in one_tier.weights_note
    flat_guide = WEIGHTS.replace(
        'confidence = "provisional"', 'confidence = "provisional"\nkind = "guide"', 1
    )
    assert to_scoring_profile(_profile(flat_guide)).weights_note


def test_an_exact_id_beats_a_variant_and_ambiguous_variants_match_nothing() -> None:
    exact = _profile(GOOD.replace('character_id = "10000002"', 'character_id = "10000007"'))
    cryo = _profile(GOOD.replace('character_id = "10000002"', 'character_id = "10000007-705"'))
    geo = _profile(GOOD.replace('character_id = "10000002"', 'character_id = "10000007-706"'))
    assert select_profile([cryo, exact], "10000007") is exact
    assert select_profile([cryo, geo], "10000007") is None  # the roster does not say which element
    assert select_profile([cryo], "10000007") is cryo  # a single variant is accepted (and flagged)


def test_in_game_beats_guide_but_only_among_equally_exact_matches() -> None:
    game_variant = _profile(
        GOOD.replace('character_id = "10000002"', 'character_id = "10000007-705"')
    )
    guide_exact = _profile(
        GOOD.replace('character_id = "10000002"', 'character_id = "10000007"').replace(
            'confidence = "provisional"', 'confidence = "provisional"\nkind = "guide"', 1
        )
    )
    assert select_profile([game_variant, guide_exact], "10000007") is guide_exact


def test_a_longer_id_that_merely_starts_with_the_digits_never_matches() -> None:
    p = _profile(GOOD.replace('character_id = "10000002"', 'character_id = "100000071"'))
    assert select_profile([p], "10000007") is None
