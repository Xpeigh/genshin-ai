"""The profile data file we ship must always load: it is hand-edited, so guard it in CI."""

from __future__ import annotations

from pathlib import Path

from genshin_companion.builds.profiles import CharacterProfile, load_profiles

SHIPPED = Path(__file__).resolve().parent.parent / "profiles" / "characters.toml"


def _load() -> list[CharacterProfile]:
    return load_profiles(SHIPPED.read_text(encoding="utf-8"))


def _by_name(kind: str) -> dict[str, CharacterProfile]:
    return {p.name: p for p in _load() if p.kind == kind}


def test_the_shipped_profiles_load_and_are_provisional_or_curated() -> None:
    profiles = _load()
    assert len(profiles) == 38
    assert {p.confidence for p in profiles} <= {"provisional", "curated"}
    assert sum(p.kind == "in-game" for p in profiles) == 28
    assert sum(p.kind == "guide" for p in profiles) == 10


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
    assert set(guides) == {
        "Mitya", "Nilou", "Qiqi", "Illuga", "Dahlia",
        "Chevreuse", "Mika", "Candace", "Fischl", "Yanfei",
    }  # fmt: skip
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
