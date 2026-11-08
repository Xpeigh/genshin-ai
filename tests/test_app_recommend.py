from __future__ import annotations

from pathlib import Path

import pytest

from genshin_companion.app import cli
from genshin_companion.app.recommend import recommend_roster, render_recommendations
from genshin_companion.builds.profiles import load_profiles
from genshin_companion.enka.models import ImportedWeapon
from helpers import snapshot
from test_app_score import TEXT, _hero, _roster, _sands
from test_builds_profiles import WEAPON_BLOCK

P = "FIGHT_PROP_"
WITH_WEAPONS = load_profiles(
    TEXT + WEAPON_BLOCK
)  # Test Hero: sands HP% recommended, weapon "Test Sword" best


def _weapon(item_id: int = 11501) -> ImportedWeapon:
    return ImportedWeapon(
        item_id=item_id, level=90, refinement=3, rarity=5, name_hash=None, stats={}
    )


def _hero_with(weapon: ImportedWeapon | None, *pieces):  # type: ignore[no-untyped-def]
    return _hero(*pieces).model_copy(update={"weapon": weapon})


def _only(roster):  # type: ignore[no-untyped-def]
    (rec,) = recommend_roster(roster, snapshot(), WITH_WEAPONS)
    return rec


def test_missing_slots_and_the_equipped_weapon_are_reported() -> None:
    rec = _only(_roster(_hero_with(_weapon(), _sands(["501062"]))))
    assert rec.name == "Test Hero" and rec.profile is not None
    assert [a.slot for a in rec.advice if a.kind == "missing"] == [
        "flower",
        "plume",
        "goblet",
        "circlet",
    ]
    assert (rec.weapon_name, rec.weapon_refinement, rec.weapon_status) == ("Test Sword", 3, "best")


@pytest.mark.parametrize(
    ("weapon", "status"),
    [(None, "unknown"), (_weapon(99999), "unknown")],
)
def test_an_unknown_weapon_never_produces_weapon_advice(
    weapon: ImportedWeapon | None, status: str
) -> None:
    rec = _only(_roster(_hero_with(weapon, _sands(["501062"]))))
    assert rec.weapon_status == status and all(a.kind != "weapon" for a in rec.advice)


def test_a_weapon_that_is_not_on_the_researched_list_is_flagged_and_a_listed_one_is_not() -> None:
    snap = snapshot()
    other = next(w for w in snap.weapons if w.id == "11501").model_copy(
        update={"id": "11502", "name": "Rusty Blade"}
    )
    snap = snap.model_copy(update={"weapons": [*snap.weapons, other]})
    (rec,) = recommend_roster(
        _roster(_hero_with(_weapon(11502), _sands(["501062"]))), snap, WITH_WEAPONS
    )
    assert rec.weapon_status == "not_listed" and any(a.kind == "weapon" for a in rec.advice)
    (ok,) = recommend_roster(
        _roster(_hero_with(_weapon(11501), _sands(["501062"]))), snap, WITH_WEAPONS
    )
    assert ok.weapon_status == "best" and all(a.kind != "weapon" for a in ok.advice)


def test_a_profile_with_no_weapon_list_says_so() -> None:
    (rec,) = recommend_roster(
        _roster(_hero_with(_weapon(), _sands(["501062"]))), snapshot(), load_profiles(TEXT)
    )
    assert rec.weapon_status == "no_list"


def test_a_character_without_a_profile_is_listed_and_not_advised() -> None:
    (rec,) = recommend_roster(
        _roster(_hero(_sands([]), avatar_id=10000099)), snapshot(), WITH_WEAPONS
    )
    assert rec.profile is None and rec.advice == ()
    assert "no profile" in render_recommendations([rec])


def test_the_report_shows_the_recommendation_the_build_and_what_to_do_first() -> None:
    wrong_set = _sands(["501062"]).model_copy(
        update={"set_id": 99999}
    )  # a set the profile does not recommend
    text = render_recommendations([_only(_roster(_hero_with(_weapon(), wrong_set)))])
    assert (
        "Test Hero  Lv50" in text
        and "[provisional, in-game profile read 2026-11-08, game data 7.2]" in text
    )
    assert "weapon: Test Sword (best;" in text and "equipped weapon: Test Sword (R3)" in text
    assert "what to do first:" in text
    assert "1. flower: no piece equipped" in text
    assert "not a recommended set" in text and "Test Set" in text


def test_a_well_built_character_has_nothing_to_flag_beyond_the_weakest_rolls() -> None:
    text = render_recommendations([_only(_roster(_hero_with(_weapon(), _sands(["501062"]))))])
    assert "no piece equipped" in text  # the other four slots are empty in this fixture
    assert "weakest substat rolls: sands (+4, still being upgraded)" in text
    assert "of a perfect roll per roll on average" in text


def test_untrusted_text_in_the_report_is_sanitised() -> None:
    snap = snapshot()
    chars = [c.model_copy(update={"name": "Hero\x1b[2J"}) for c in snap.characters]
    sets = [s.model_copy(update={"name": "Set\x1b[31m"}) for s in snap.artifact_sets]
    snap = snap.model_copy(update={"characters": chars, "artifact_sets": sets})
    wrong_set = _sands(["501062"])
    text = render_recommendations(
        recommend_roster(_roster(_hero_with(_weapon(), wrong_set)), snap, WITH_WEAPONS)
    )
    assert "\x1b" not in text


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(h))
    monkeypatch.setattr(cli, "_current_snapshot", lambda _layout: snapshot())
    folder = h / "user" / "rosters"
    folder.mkdir(parents=True)
    (folder / "123456789.json").write_text(
        _roster(_hero_with(_weapon(), _sands(["501062"]))).model_dump_json(), encoding="utf-8"
    )
    (h.parent / "p.toml").write_text(TEXT + WEAPON_BLOCK, encoding="utf-8")
    return h


def test_recommend_command_prints_a_report_and_filters_by_name(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profiles = str(home.parent / "p.toml")
    assert cli.main(["recommend", "--profiles", profiles]) == 0
    assert "Test Hero" in capsys.readouterr().out
    assert (
        cli.main(["recommend", "--profiles", profiles, "--character", "test hero"]) == 0
    )  # case-insensitive
    assert "what to do first" in capsys.readouterr().out
    assert cli.main(["recommend", "--profiles", profiles, "--character", "Nobody"]) == 1
    assert "Nobody" in capsys.readouterr().err


def test_recommend_command_explains_missing_pieces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(tmp_path / "home"))
    assert cli.main(["recommend"]) == 1  # no roster imported
    assert "import" in capsys.readouterr().err
    folder = tmp_path / "home" / "user" / "rosters"
    folder.mkdir(parents=True)
    (folder / "123456789.json").write_text(_roster(_hero()).model_dump_json(), encoding="utf-8")
    assert cli.main(["recommend"]) == 1  # a roster but no data snapshot
    assert "sync" in capsys.readouterr().err
    monkeypatch.setattr(cli, "_current_snapshot", lambda _layout: snapshot())
    assert cli.main(["recommend", "--profiles", str(tmp_path / "missing.toml")]) == 1
    assert capsys.readouterr().out == ""


def test_several_pieces_from_unrecommended_sets_are_one_line() -> None:
    sands = _sands(["501062"]).model_copy(update={"set_id": 99999})
    flower = sands.model_copy(update={"slot": "EQUIP_BRACER", "item_id": 2})
    text = render_recommendations([_only(_roster(_hero_with(_weapon(), sands, flower)))])
    grouped = [ln for ln in text.splitlines() if "not recommended sets" in ln]
    assert len(grouped) == 1 and "flower" in grouped[0] and "sands" in grouped[0]
    assert "Test Set" in grouped[0]
    assert "is not a recommended set" not in text  # no per-piece duplicates
