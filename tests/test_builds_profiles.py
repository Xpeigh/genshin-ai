from __future__ import annotations

import pytest

from genshin_companion.builds.profiles import (
    ProfileError,
    load_profiles,
    validate_profiles,
)
from helpers import snapshot

HEADER = """
[[profile]]
character_id = "10000002"
name = "Test Hero"
role = "main DPS"
observed_at = "2026-11-08"
game_version = "7.2"
source = "in-game recommendation (usage statistics from recently active players), read by Ben"
confidence = "provisional"
"""

# Ordered tiers: best first, a tier holds ties. A bare string is an unconditional stat; an inline
# table adds a condition. Scalar keys must come before sub-tables in TOML.
GOOD = (
    HEADER
    + """
notes = ["ER target about 120%"]
substat_tiers = [
    ["FIGHT_PROP_ATTACK_PERCENT"],
    [{ stat = "FIGHT_PROP_HP", condition = "only with a test weapon" }],
]

[[profile.recommended_sets]]
sets = ["Test Set"]
usage_percent = 70.1

[[profile.recommended_sets]]
sets = ["Test Set", "Test Set Two"]
tier = "alternative"
condition = "if nobody else uses the first set"

[[profile.references]]
name = "Test Guide"
url = "https://example.com/guide"

[profile.recommended_main_stats]
sands = ["FIGHT_PROP_ATTACK_PERCENT"]
goblet = ["FIGHT_PROP_HP"]
circlet = ["FIGHT_PROP_ATTACK_PERCENT", { stat = "FIGHT_PROP_HP", condition = "only at C6" }]
"""
)

WEIGHTS = (
    HEADER
    + """
recommended_sets = []

[profile.substat_weights]
FIGHT_PROP_HP = 0.5
FIGHT_PROP_ATTACK_PERCENT = 1.0
"""
)


def test_loads_a_weights_profile_with_provenance() -> None:
    (p,) = load_profiles(WEIGHTS)
    assert p.character_id == "10000002" and p.confidence == "provisional"
    assert p.substat_weights["FIGHT_PROP_ATTACK_PERCENT"] == 1.0
    assert "recently active players" in p.source and p.observed_at.isoformat() == "2026-11-08"


def test_loads_ordered_tiers_keeping_order_and_conditions() -> None:
    (p,) = load_profiles(GOOD)
    assert [[c.stat for c in tier] for tier in p.substat_tiers] == [
        ["FIGHT_PROP_ATTACK_PERCENT"],
        ["FIGHT_PROP_HP"],
    ]
    assert p.substat_tiers[0][0].condition is None
    assert p.substat_tiers[1][0].condition == "only with a test weapon"
    assert p.substat_weights == {}


def test_main_stats_keep_unconditional_and_conditional_choices() -> None:
    (p,) = load_profiles(GOOD)
    circlet = p.recommended_main_stats["circlet"]
    assert [(c.stat, c.condition) for c in circlet] == [
        ("FIGHT_PROP_ATTACK_PERCENT", None),
        ("FIGHT_PROP_HP", "only at C6"),
    ]


def test_sets_distinguish_best_from_alternative_and_two_piece_pairs() -> None:
    (p,) = load_profiles(GOOD)
    assert [(o.sets, o.tier) for o in p.recommended_sets] == [
        (["Test Set"], "best"),
        (["Test Set", "Test Set Two"], "alternative"),
    ]
    assert p.recommended_sets[1].condition == "if nobody else uses the first set"


def test_references_are_recorded_but_never_fetched() -> None:
    (p,) = load_profiles(GOOD)
    assert p.references[0].name == "Test Guide" and p.references[0].url.startswith("https://")


@pytest.mark.parametrize(
    "bad",
    [
        GOOD.replace('confidence = "provisional"', 'confidence = "verified"'),  # never hand-set
        WEIGHTS.replace("FIGHT_PROP_HP = 0.5", "FIGHT_PROP_HP = 7.0"),  # weight out of range
        GOOD.replace('observed_at = "2026-11-08"\n', ""),  # provenance is required
        GOOD.replace('source = "in-game', 'extra = 1\nsource = "in-game'),  # unknown key
        WEIGHTS.replace("FIGHT_PROP_HP = 0.5", "CRIT_RATE = 1.0"),  # not a canonical stat id
        GOOD.replace('["FIGHT_PROP_ATTACK_PERCENT"],\n    [{', '["CRIT_RATE"],\n    [{'),
        HEADER,  # neither weights nor tiers
        GOOD + "\n[profile.substat_weights]\nFIGHT_PROP_HP = 1.0\n",  # both: two sources of truth
        GOOD.replace('["FIGHT_PROP_ATTACK_PERCENT"],\n    [{', "[],\n    [{"),  # empty tier
        GOOD.replace(
            '[{ stat = "FIGHT_PROP_HP", condition = "only with a test weapon" }]',
            '["FIGHT_PROP_ATTACK_PERCENT"]',
        ),  # stat repeated across tiers
        GOOD.replace('condition = "only with a test weapon"', 'condition = ""'),  # empty condition
        GOOD.replace('sets = ["Test Set", "Test Set Two"]', 'sets = ["A", "B", "C"]'),  # 3 sets
        GOOD.replace('sets = ["Test Set", "Test Set Two"]', 'sets = ["Test Set", "Test Set"]'),
        GOOD.replace('sets = ["Test Set"]\n', "sets = []\n", 1),  # empty set option
        GOOD.replace('tier = "alternative"', 'tier = "meta"'),
        GOOD.replace("https://example.com/guide", "http://example.com/guide"),  # https only
        GOOD.replace("https://example.com/guide", "https://user:pw@example.com/guide"),  # no creds
        GOOD.replace("https://example.com/guide", "https:///guide"),  # no host
        GOOD.replace("sands = [", "flower = [", 1),  # only sands/goblet/circlet vary
        GOOD.replace(
            'sands = ["FIGHT_PROP_ATTACK_PERCENT"]', 'sands = ["FIGHT_PROP_HP", "FIGHT_PROP_HP"]'
        ),
        "[[profile]]\ncharacter_id = 5",
        "not toml [[[",
    ],
)
def test_malformed_profiles_are_rejected(bad: str) -> None:
    with pytest.raises(ProfileError):
        load_profiles(bad)


def test_a_valid_profile_has_no_problems_against_the_snapshot() -> None:
    text = GOOD.replace(', "Test Set Two"', "")
    assert validate_profiles(load_profiles(text), snapshot()) == []


def test_unknown_character_set_stat_or_main_stat_is_reported_not_guessed() -> None:
    bad = (
        GOOD.replace('"10000002"', '"99999999"')
        .replace('sets = ["Test Set"]\n', 'sets = ["Nonexistent Set"]\n', 1)
        .replace('sets = ["Test Set", "Test Set Two"]', 'sets = ["Other Missing", "Test Set"]')
        .replace(
            '["FIGHT_PROP_ATTACK_PERCENT"],\n    [{',
            '["FIGHT_PROP_ICE_ADD_HURT"],\n    [{',
        )
        .replace('goblet = ["FIGHT_PROP_HP"]', 'goblet = ["FIGHT_PROP_NOT_A_MAIN_STAT"]')
    )
    text = "\n".join(validate_profiles(load_profiles(bad), snapshot()))
    assert "99999999" in text
    assert "Nonexistent Set" in text and "Other Missing" in text
    assert "FIGHT_PROP_ICE_ADD_HURT" in text and "FIGHT_PROP_NOT_A_MAIN_STAT" in text


def test_weights_with_an_unrollable_stat_are_reported() -> None:
    bad = WEIGHTS.replace("FIGHT_PROP_HP = 0.5", "FIGHT_PROP_ICE_ADD_HURT = 1.0")
    assert "FIGHT_PROP_ICE_ADD_HURT" in "\n".join(validate_profiles(load_profiles(bad), snapshot()))


def test_duplicate_characters_are_rejected() -> None:
    with pytest.raises(ProfileError, match="duplicate"):
        load_profiles(GOOD + GOOD)


def test_profile_for_an_older_game_version_is_flagged_stale() -> None:
    old = GOOD.replace('game_version = "7.2"', 'game_version = "7.0"')
    problems = validate_profiles(load_profiles(old), snapshot())
    assert any("7.0" in p and "7.2" in p for p in problems)


# --- hardening: profile files may come from third parties, so treat them as untrusted ---------


@pytest.mark.parametrize(
    "bad",
    [
        GOOD.replace('name = "Test Hero"', 'name = "Hero\u001b[2J"'),  # terminal escape
        GOOD.replace('name = "Test Hero"', 'name = "x\nsubstats: forged"'),  # forged line
        GOOD.replace('role = "main DPS"', 'role = "x\u202eevil"'),  # bidi override
        GOOD.replace('name = "Test Hero"', 'name = "   "'),  # blank
        GOOD.replace("ER target about 120%", "  "),  # blank note
        GOOD.replace('condition = "only at C6"', 'condition = "   "'),  # blank condition
        GOOD.replace("Test Guide", "Guide\rforged"),  # carriage return in a reference name
        GOOD.replace('sets = ["Test Set"]\n', 'sets = ["Set\u0007"]\n', 1),  # bell in a set name
        GOOD.replace(
            '"FIGHT_PROP_ATTACK_PERCENT"],\n    [{', '"FIGHT_PROP_ATTACK_PERCENT\n"],\n    [{'
        ),
        WEIGHTS.replace("FIGHT_PROP_HP = 0.5", '"FIGHT_PROP_HP\n" = 0.5'),  # trailing newline
        GOOD.replace('stat = "FIGHT_PROP_HP",', 'stat = "FIGHT_PROP_' + "A" * 100 + '",'),  # length
        GOOD.replace('character_id = "10000002"', 'character_id = "010000002"'),  # leading zero
        GOOD.replace('game_version = "7.2"', 'game_version = "٧.٢"'),  # non-ASCII digits
        GOOD.replace('sands = ["FIGHT_PROP_ATTACK_PERCENT"]', "sands = []"),  # empty slot list
        WEIGHTS.replace("FIGHT_PROP_HP = 0.5", "FIGHT_PROP_HP = 0.0").replace(
            "FIGHT_PROP_ATTACK_PERCENT = 1.0", "FIGHT_PROP_ATTACK_PERCENT = 0.0"
        ),  # all zero
        WEIGHTS.replace("FIGHT_PROP_HP = 0.5", "FIGHT_PROP_HP = true"),  # bool is not a weight
        GOOD.replace("[[profile]]", "[[profiles]]"),  # mistyped table: nothing would load
        GOOD + "\n[extra]\nx = 1\n",  # unknown top-level table
        "",  # an empty file has no profiles
        "# only a comment\n",
        "a = " + "[" * 100_000 + "]" * 100_000,  # parser recursion
        "a = " + "{a=" * 5_000 + "1" + "}" * 5_000,
    ],
)
def test_untrusted_profile_text_is_rejected_cleanly(bad: str) -> None:
    with pytest.raises(ProfileError):
        load_profiles(bad)


def test_too_many_items_are_rejected() -> None:
    many_tiers = "substat_tiers = [\n" + '    ["FIGHT_PROP_HP"],\n' * 40 + "]\n"
    with pytest.raises(ProfileError):
        load_profiles(HEADER + many_tiers)
    keys = ["FIGHT_PROP_" + chr(65 + i // 26) + chr(65 + i % 26) for i in range(200)]
    many_weights = HEADER + "[profile.substat_weights]\n" + "".join(f"{k} = 1.0\n" for k in keys)
    with pytest.raises(ProfileError):
        load_profiles(many_weights)
    with pytest.raises(ProfileError):
        load_profiles((WEIGHTS + "\n") * 600)


def test_a_wrong_name_for_a_known_character_id_is_reported() -> None:
    text = GOOD.replace(', "Test Set Two"', "").replace('name = "Test Hero"', 'name = "Somebody"')
    problems = validate_profiles(load_profiles(text), snapshot())
    assert any("Somebody" in p and "Test Hero" in p for p in problems)


# --- kind (in-game vs guide) and the game's usage percentage ---------------------------------


def _as_guide(text: str) -> str:
    return text.replace(
        'confidence = "provisional"', 'confidence = "provisional"\nkind = "guide"', 1
    )


def test_kind_defaults_to_in_game_and_guides_are_marked() -> None:
    assert load_profiles(GOOD)[0].kind == "in-game"
    assert load_profiles(_as_guide(GOOD))[0].kind == "guide"


def test_one_profile_per_character_and_kind() -> None:
    both = load_profiles(GOOD + _as_guide(GOOD))
    assert {p.kind for p in both} == {"in-game", "guide"}
    with pytest.raises(ProfileError, match="duplicate"):
        load_profiles(_as_guide(GOOD) + _as_guide(GOOD))


def test_an_unknown_kind_is_rejected() -> None:
    with pytest.raises(ProfileError):
        load_profiles(
            GOOD.replace(
                'confidence = "provisional"', 'confidence = "provisional"\nkind = "rumour"', 1
            )
        )


def test_usage_percent_is_kept_and_bounded() -> None:
    (p,) = load_profiles(GOOD)
    assert p.recommended_sets[0].usage_percent == 70.1
    assert p.recommended_sets[1].usage_percent is None
    for bad in ("-1", "100.5", "true", '"70"'):
        with pytest.raises(ProfileError):
            load_profiles(GOOD.replace("usage_percent = 70.1", f"usage_percent = {bad}"))


# --- usage percentages on main stats ----------------------------------------------------------

SANDS_WITH_PCT = 'sands = ["FIGHT_PROP_ATTACK_PERCENT"]'


def _with_sands(entries: str) -> str:
    return GOOD.replace(SANDS_WITH_PCT, f"sands = [{entries}]")


def test_main_stats_keep_the_games_usage_percent() -> None:
    text = _with_sands(
        '{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = 82.5 }, '
        '{ stat = "FIGHT_PROP_HP", usage_percent = 4.8 }'
    )
    (p,) = load_profiles(text)
    assert [(c.stat, c.usage_percent) for c in p.recommended_main_stats["sands"]] == [
        ("FIGHT_PROP_ATTACK_PERCENT", 82.5),
        ("FIGHT_PROP_HP", 4.8),
    ]
    assert validate_profiles(load_profiles(text.replace(', "Test Set Two"', "")), snapshot()) == []


def test_a_bare_main_stat_has_no_percent() -> None:
    (p,) = load_profiles(GOOD)
    assert p.recommended_main_stats["sands"][0].usage_percent is None


@pytest.mark.parametrize(
    "entries",
    [
        # exclusive choices cannot add up to more than 100% (rounding tolerance only)
        '{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = 90 }, '
        '{ stat = "FIGHT_PROP_HP", usage_percent = 20 }',
        '{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = -1 }',
        '{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = 100.5 }',
        '{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = true }',
        '{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = "82" }',
    ],
)
def test_bad_main_stat_percentages_are_rejected(entries: str) -> None:
    with pytest.raises(ProfileError):
        load_profiles(_with_sands(entries))


def test_a_percent_on_a_substat_is_rejected() -> None:
    bad = GOOD.replace(
        '["FIGHT_PROP_ATTACK_PERCENT"],\n    [{',
        '[{ stat = "FIGHT_PROP_ATTACK_PERCENT", usage_percent = 50 }],\n    [{',
    )
    assert bad != GOOD
    with pytest.raises(ProfileError):
        load_profiles(bad)
