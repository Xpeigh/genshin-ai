"""The profile data file we ship must always load: it is hand-edited, so guard it in CI."""

from __future__ import annotations

from pathlib import Path

import pytest

from genshin_companion.builds.profiles import CharacterProfile, load_profiles

SHIPPED = Path(__file__).resolve().parent.parent / "profiles" / "characters.toml"


def _load() -> list[CharacterProfile]:
    return load_profiles(SHIPPED.read_text(encoding="utf-8"))


def _by_name(kind: str) -> dict[str, CharacterProfile]:
    return {p.name: p for p in _load() if p.kind == kind}


def test_the_shipped_profiles_load_and_are_provisional_or_curated() -> None:
    profiles = _load()
    assert len(profiles) == 125
    assert {p.confidence for p in profiles} <= {"provisional", "curated"}
    assert sum(p.kind == "in-game" for p in profiles) == 28
    assert sum(p.kind == "guide" for p in profiles) == 97


def test_in_game_profiles_say_where_they_came_from() -> None:
    for p in _by_name("in-game").values():
        assert "recently active players" in p.source
        assert len(p.substat_tiers) == 1 and 2 <= len(p.substat_tiers[0]) <= 4
        assert p.recommended_sets


def test_spot_checks_against_the_screenshot_of_the_in_game_table() -> None:
    game = _by_name("in-game")
    vesna = game["Vesna"]
    assert vesna.recommended_sets[0].sets == ["Scarlet Proof"]
    assert vesna.recommended_sets[0].usage_percent == 94.8
    assert game["Noelle"].recommended_sets[1].sets == ["Gladiator's Finale"]
    assert game["Noelle"].recommended_sets[1].usage_percent == 14.8
    # two 2-piece sets in one option
    assert game["Charlotte"].recommended_sets[0].sets == [
        "Gladiator's Finale",
        "Emblem of Severed Fate",
    ]
    assert game["Xinyan"].recommended_sets[1].sets == ["Bloodstained Chivalry", "Pale Flame"]
    # the game showed no percentage for these
    assert game["Valeriy"].recommended_sets[0].usage_percent is None
    assert game["Amber"].recommended_sets[0].usage_percent is None
    # fewer than four favoured stats are recorded as shown
    assert len(game["Yun Jin"].substat_tiers[0]) == 3 and len(game["Barbara"].substat_tiers[0]) == 3


def test_guide_profiles_cite_where_they_came_from() -> None:
    guides = _by_name("guide")
    sheet = {
        "Mitya", "Nilou", "Qiqi", "Illuga", "Dahlia",
        "Chevreuse", "Mika", "Candace", "Fischl", "Yanfei",
    }  # fmt: skip
    assert sheet <= set(guides)  # the friend's sheet profiles are still there
    for p in guides.values():
        assert p.references, f"{p.name} has no cited source"
        assert p.substat_tiers and not p.substat_weights
        assert "not the in-game recommendation" in p.source


def test_mika_and_dahlia_have_both_kinds_and_they_differ() -> None:
    # same character, two sources that disagree: kept apart, never merged
    for name in ("Mika", "Dahlia"):
        game, guide = _by_name("in-game")[name], _by_name("guide")[name]
        assert game.character_id == guide.character_id
        assert game.substat_tiers != guide.substat_tiers


def _mains(name: str, slot: str) -> list[tuple[str, float | None]]:
    return [
        (c.stat, c.usage_percent) for c in _by_name("in-game")[name].recommended_main_stats[slot]
    ]


def test_every_in_game_profile_has_sands_goblet_and_circlet_main_stats() -> None:
    for p in _by_name("in-game").values():
        assert set(p.recommended_main_stats) == {"sands", "goblet", "circlet"}, p.name
        for slot, choices in p.recommended_main_stats.items():
            assert 1 <= len(choices) <= 3, (p.name, slot)


def test_main_stat_spot_checks_against_the_screenshots() -> None:
    p = "FIGHT_PROP_"
    assert _mains("Vesna", "sands") == [
        (p + "ATTACK_PERCENT", 93.6),
        (p + "ELEMENT_MASTERY", 2.7),
        (p + "HP_PERCENT", 1.6),
    ]
    assert _mains("Vesna", "goblet")[1] == (p + "WIND_ADD_HURT", 3.2)
    assert _mains("Yun Jin", "sands")[0] == (p + "DEFENSE_PERCENT", 76.5)
    assert _mains("Barbara", "circlet")[0] == (p + "HEAL_ADD", 66.0)
    assert _mains("Xinyan", "goblet")[0] == (p + "PHYSICAL_ADD_HURT", 55.9)
    # Valeriy: the game listed the stats but no percentages yet
    assert _mains("Valeriy", "sands") == [
        (p + "ATTACK_PERCENT", None),
        (p + "CHARGE_EFFICIENCY", None),
    ]
    assert _mains("Valeriy", "circlet") == [(p + "ATTACK_PERCENT", None)]


def test_in_game_main_stat_shares_never_exceed_100_percent() -> None:
    for p in _by_name("in-game").values():
        for slot, choices in p.recommended_main_stats.items():
            assert sum(c.usage_percent or 0.0 for c in choices) <= 100.5, (p.name, slot)


KNOWN_WEAPON_HOSTS = {
    "game8.co", "gamewith.net", "genshin-builds.com", "genshin.gg", "keqingmains.com", "www.pockettactics.com",
}  # fmt: skip


def _is_current(as_of: str) -> bool:
    return "stale" not in as_of and as_of != "undated"


def test_every_in_game_profile_has_cited_weapons() -> None:
    for p in _by_name("in-game").values():
        assert 3 <= len(p.recommended_weapons) <= 6, p.name
        assert len({w.name for w in p.recommended_weapons}) == len(p.recommended_weapons)


def test_a_best_weapon_is_backed_by_two_current_pages() -> None:
    for p in _by_name("in-game").values():
        assert any(w.tier == "best" for w in p.recommended_weapons), f"{p.name} has no best weapon"
    for p in _load():  # in-game and guide profiles alike: "best" means two current pages ...
        best = [w for w in p.recommended_weapons if w.tier == "best"]
        for w in best:
            current = [s for s in w.sources if _is_current(s.as_of)]
            if len(current) >= 2:
                assert min(s.rank for s in current) <= 3, (p.name, w.name)
            else:  # ... unless the character has a single current source, and then the profile says so
                assert len(current) == 1, (p.name, w.name)
                assert any("Only one current source lists weapons" in n for n in p.notes), p.name
                assert w.sources[0].rank == 1 or current[0].rank == 1, (p.name, w.name)


def test_weapon_sources_come_from_the_documented_research_hosts() -> None:
    from urllib.parse import urlsplit

    for p in _by_name("in-game").values():
        for w in p.recommended_weapons:
            for s in w.sources:
                assert urlsplit(s.url).hostname in KNOWN_WEAPON_HOSTS, (p.name, s.url)
                assert s.accessed.isoformat() == "2026-11-08"


def test_weapon_spot_checks_against_the_research() -> None:
    vesna = _by_name("in-game")["Vesna"]
    assert vesna.recommended_weapons[0].name == "Beyond the Chrysalis"
    assert {s.name for s in vesna.recommended_weapons[0].sources} == {"GenshinBuilds", "GameWith"}
    yun = {w.name for w in _by_name("in-game")["Yun Jin"].recommended_weapons}
    assert "Prototype Starglitter" in yun


KNOWN_GUIDE_HOSTS = KNOWN_WEAPON_HOSTS | {"hoyobuild.com", "kaption.one", "timesaver.gg"}


def test_every_researched_source_comes_from_a_documented_research_host() -> None:
    from urllib.parse import urlsplit

    for p in _by_name("guide").values():
        weapon_urls = [s.url for w in p.recommended_weapons for s in w.sources]
        # the friend's sheet profiles cite the sheet's own sites; the research batch cites these hosts
        reference_urls = [r.url for r in p.references] if "second agent" in p.source else []
        urls = weapon_urls + reference_urls
        assert urls or "second agent" not in p.source, p.name
        for url in urls:
            assert urlsplit(url).hostname in KNOWN_GUIDE_HOSTS, (p.name, url)


def test_guide_profiles_that_list_weapons_cite_current_pages_for_every_best_set_or_say_why() -> (
    None
):
    # a profile whose current sources disagree on the best set must say so instead of picking one
    for p in _by_name("guide").values():
        options = p.recommended_sets
        if options and not any(o.tier == "best" for o in options):
            assert any("do not agree" in n for n in p.notes), p.name


def test_every_playable_character_has_a_profile() -> None:
    import os

    path = os.environ.get("GENSHIN_REAL_SNAPSHOT")
    if not path:
        pytest.skip("set GENSHIN_REAL_SNAPSHOT to run")
    from genshin_companion.data.models import Snapshot

    snap = Snapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))
    have = {p.character_id.split("-")[0] for p in _load()}
    playable = {
        c.id
        for c in snap.characters
        if c.name and c.weapon_type and "-" not in c.id and c.name != "Manekin"
    }
    assert playable <= have, sorted(playable - have)


def test_a_single_source_best_set_or_weapon_is_always_flagged() -> None:
    for p in _by_name("guide").values():
        has_best_set = any(o.tier == "best" for o in p.recommended_sets)
        flagged = any("Only one current source names a best set" in n for n in p.notes)
        disagree = any("do not agree" in n for n in p.notes)
        assert not (flagged and disagree), p.name  # one reason or the other, never both
        if p.recommended_sets and not has_best_set:
            assert disagree, p.name  # no best set always comes with the reason
        if flagged:
            assert has_best_set, p.name


def test_the_seven_single_source_sets_and_three_single_source_weapons_were_promoted() -> None:
    guides = _by_name("guide")
    for name in ("Dehya", "Ganyu", "Kamisato Ayaka", "Keqing", "Mona", "Sigewinne", "Zhongli"):
        assert any("Only one current source names a best set" in n for n in guides[name].notes), (
            name
        )
        assert any(o.tier == "best" for o in guides[name].recommended_sets), name
    for name in ("Kaedehara Kazuha", "Raiden Shogun", "Yaoyao"):
        assert any("Only one current source lists weapons" in n for n in guides[name].notes), name
        assert sum(w.tier == "best" for w in guides[name].recommended_weapons) == 1, name
