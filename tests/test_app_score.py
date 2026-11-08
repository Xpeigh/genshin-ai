from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from genshin_companion.app import cli
from genshin_companion.app.score import render_scores, score_roster
from genshin_companion.builds.profiles import load_profiles
from genshin_companion.enka.models import (
    ImportedArtifact,
    ImportedCharacter,
    ImportedSubstat,
    Roster,
)
from helpers import snapshot
from test_builds_profiles import GOOD

P = "FIGHT_PROP_"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def _sands(rolls: list[str], level: int = 4) -> ImportedArtifact:
    return ImportedArtifact(
        item_id=1,
        slot="EQUIP_SHOES",
        rarity=5,
        level=level,
        set_id=15025,  # "Test Set" in the synthetic snapshot
        set_name_hash=None,
        main_stat=P + "HP_PERCENT",
        main_value=20.1,
        substats=[ImportedSubstat(stat=P + "ATTACK_PERCENT", value=6.0)],
        roll_affix_ids=rolls,
    )


def _roster(*characters: ImportedCharacter) -> Roster:
    return Roster(
        uid="123456789", region=None, nickname=None, player_level=None, ttl=60, fetched_at=NOW,
        source="file", showcase_open=True, showcase_size=len(characters), characters=list(characters), notes=[],
    )  # fmt: skip


def _hero(*arts: ImportedArtifact, avatar_id: int = 10000002) -> ImportedCharacter:
    return ImportedCharacter(
        avatar_id=avatar_id, level=50, constellation=0, weapon=None, artifacts=list(arts)
    )


# sands main stat HP% is the recommended one here, so ATK% (favoured) can appear as a substat
TEXT = GOOD.replace(', "Test Set Two"', "").replace(
    'sands = ["FIGHT_PROP_ATTACK_PERCENT"]', 'sands = ["FIGHT_PROP_HP_PERCENT"]'
)
PROFILES = load_profiles(TEXT)


def test_a_roster_piece_is_scored_with_the_selected_profile() -> None:
    # roll 501062 = ATK% 0.06 (best five-star roll, value 1.0); 501022 = HP 300, a conditional stat
    roster = _roster(_hero(_sands(["501062", "501022"])))
    (result,) = score_roster(roster, snapshot(), PROFILES)
    assert result.name == "Test Hero" and result.profile is not None
    (piece,) = result.pieces
    s = piece.score
    assert piece.slot == "sands"
    assert s.roll_score == pytest.approx(1.0) and (s.total_rolls, s.useful_rolls) == (2, 1)
    assert [(n.stat, n.rolls) for n in s.not_scored] == [(P + "HP", 1)]
    assert (s.main_stat_fit.status, s.set_fit.status, s.set_fit.usage_percent) == (
        "recommended",
        "best",
        70.1,
    )
    assert result.summary is not None and result.summary.pieces_scored == 1


def test_a_character_without_a_profile_is_listed_but_not_scored() -> None:
    roster = _roster(_hero(_sands(["501062"]), avatar_id=10000099))
    (result,) = score_roster(roster, snapshot(), PROFILES)
    assert result.profile is None and result.pieces == () and result.summary is None
    assert "no profile" in render_scores([result])


def test_a_slot_the_importer_does_not_know_is_reported_not_dropped() -> None:
    odd = _sands([]).model_copy(update={"slot": "EQUIP_MYSTERY"})
    (result,) = score_roster(_roster(_hero(odd)), snapshot(), PROFILES)
    assert result.pieces == () and any("EQUIP_MYSTERY" in n for n in result.notes)


def test_the_report_shows_scores_fits_conditions_and_provenance() -> None:
    roster = _roster(_hero(_sands(["501062", "501022"])))
    text = render_scores(score_roster(roster, snapshot(), PROFILES))
    assert "Test Hero" in text and "[provisional, in-game" in text
    assert "roll score 1.00" in text and "2 rolls, 1 on favoured stats" in text
    assert (
        "main stat: HP% is recommended" in text and "set: Test Set (best, 70.1% of players)" in text
    )
    assert "not scored: HP (only with a test weapon) on 1 roll" in text
    assert "missing: flower, plume, goblet, circlet" in text
    assert "weakest: sands" in text


def test_score_command_explains_missing_roster_and_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(tmp_path / "home"))
    assert cli.main(["score"]) == 1
    assert "import" in capsys.readouterr().err
    # a roster exists but no data snapshot has been synced
    folder = tmp_path / "home" / "user" / "rosters"
    folder.mkdir(parents=True)
    (folder / "123456789.json").write_text(_roster(_hero()).model_dump_json(), encoding="utf-8")
    assert cli.main(["score"]) == 1
    assert "sync" in capsys.readouterr().err


def test_score_command_prints_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(tmp_path / "home"))
    folder = tmp_path / "home" / "user" / "rosters"
    folder.mkdir(parents=True)
    (folder / "123456789.json").write_text(
        _roster(_hero(_sands(["501062"]))).model_dump_json(), encoding="utf-8"
    )
    profiles = tmp_path / "p.toml"
    profiles.write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr(cli, "_current_snapshot", lambda _layout: snapshot())
    assert cli.main(["score", "--profiles", str(profiles)]) == 0
    out = capsys.readouterr().out
    assert "Test Hero" in out and "roll score 1.00" in out


# --- review hardening (2026-11-08) ------------------------------------------------------------


def _save_roster(home: Path, roster: Roster, uid: str = "123456789") -> None:
    folder = home / "user" / "rosters"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{uid}.json").write_text(roster.model_dump_json(), encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(h))
    monkeypatch.setattr(cli, "_current_snapshot", lambda _layout: snapshot())
    return h


def test_every_equipment_slot_maps_to_its_scoring_slot() -> None:
    slots = {
        "EQUIP_BRACER": "flower", "EQUIP_NECKLACE": "plume", "EQUIP_SHOES": "sands",
        "EQUIP_RING": "goblet", "EQUIP_DRESS": "circlet",
    }  # fmt: skip
    for equip, expected in slots.items():
        art = _sands([]).model_copy(update={"slot": equip})
        (result,) = score_roster(_roster(_hero(art)), snapshot(), PROFILES)
        assert [p.slot for p in result.pieces] == [expected], equip


def test_pieces_are_reported_in_game_order_and_a_duplicate_slot_is_noted() -> None:
    flower = _sands([]).model_copy(update={"slot": "EQUIP_BRACER", "item_id": 2})
    again = _sands([]).model_copy(update={"item_id": 3})
    (result,) = score_roster(_roster(_hero(_sands([]), flower, again)), snapshot(), PROFILES)
    assert [p.slot for p in result.pieces] == ["flower", "sands"]
    assert any("second piece in slot sands" in n for n in result.notes)


def test_a_four_star_piece_is_scored_as_a_four_star() -> None:
    art = _sands(["501062"]).model_copy(update={"rarity": 4})  # a 5-star roll id on a 4-star piece
    (result,) = score_roster(_roster(_hero(art)), snapshot(), PROFILES)
    assert result.pieces[0].score.roll_score == 0.0 and result.pieces[0].score.problems


@pytest.mark.parametrize(
    "mutation",
    [
        {"main_stat": "BOGUS"},
        {"roll_affix_ids": ["501062"] * 20},
        {"roll_affix_ids": ["50106\x1b[2J"]},
    ],
)
def test_malformed_roster_pieces_become_notes_not_crashes(mutation: dict[str, object]) -> None:
    art = _sands(["501062"]).model_copy(update=mutation)
    good = _sands(["501062"]).model_copy(update={"slot": "EQUIP_BRACER", "item_id": 9})
    (result,) = score_roster(_roster(_hero(art, good)), snapshot(), PROFILES)
    assert [p.slot for p in result.pieces] == ["flower"]  # the good piece is still scored
    assert any("not scored" in n for n in result.notes)


def test_untrusted_text_never_reaches_the_output_as_control_characters() -> None:
    evil_slot = _sands([]).model_copy(update={"slot": "EQUIP_\x1b[2J\x1b]0;pwned\x07"})
    snap = snapshot()
    sets = [
        s.model_copy(update={"name": "Set\x1b[31m"}) if s.id == "15025" else s
        for s in snap.artifact_sets
    ]
    chars = [c.model_copy(update={"name": "Hero\x1b[2J"}) for c in snap.characters]
    snap = snap.model_copy(update={"artifact_sets": sets, "characters": chars})
    text = render_scores(
        score_roster(_roster(_hero(evil_slot, _sands(["501062"]))), snap, PROFILES)
    )
    assert "\x1b" not in text and "\x07" not in text
    assert "Hero" in text and "Set" in text


def test_a_profile_matched_by_base_id_is_flagged() -> None:
    variant = load_profiles(
        TEXT.replace('character_id = "10000002"', 'character_id = "10000002-501"')
    )
    (result,) = score_roster(_roster(_hero(_sands(["501062"]))), snapshot(), variant)
    assert result.profile is not None
    assert any("10000002-501" in n and "element" in n for n in result.notes)
    assert "10000002-501" in render_scores([result])


def test_report_details_are_all_asserted() -> None:
    cond = _sands(["501062", "501022"])
    text = render_scores(score_roster(_roster(_hero(cond)), snapshot(), PROFILES))
    assert "(2 rolls, 1 on favoured stats" in text
    assert "on 1 roll\n" in text + "\n" and "on 1 rolls" not in text
    assert "crit value 0.0" in text and "set: Test Set (best" in text
    one = render_scores(score_roster(_roster(_hero(_sands(["501062"]))), snapshot(), PROFILES))
    assert "(1 roll, 1 on favoured stats" in one
    bad = render_scores(score_roster(_roster(_hero(_sands(["999999"]))), snapshot(), PROFILES))
    assert "! roll id 999999 is not in the data snapshot" in bad


def test_curated_and_provisional_headers_differ_and_guide_weights_are_noted() -> None:
    curated = load_profiles(TEXT.replace('confidence = "provisional"', 'confidence = "curated"'))
    text = render_scores(score_roster(_roster(_hero(_sands([]))), snapshot(), curated))
    assert (
        "[curated, in-game profile read 2026-11-08]" in text
        and "until a profile is approved" not in text
    )
    guide = load_profiles(
        TEXT.replace('confidence = "provisional"', 'confidence = "provisional"\nkind = "guide"', 1)
    )
    gtext = render_scores(score_roster(_roster(_hero(_sands([]))), snapshot(), guide))
    assert "note: Tier weights" in gtext and "convention" in gtext


def test_a_conditional_main_stat_is_phrased_without_repeating_only() -> None:
    cond = load_profiles(
        TEXT.replace(
            'sands = ["FIGHT_PROP_HP_PERCENT"]',
            'sands = [{ stat = "FIGHT_PROP_HP_PERCENT", condition = "only at C6" }]',
        )
    )
    text = render_scores(score_roster(_roster(_hero(_sands([]))), snapshot(), cond))
    assert "only at C6" in text and "only recommended only" not in text and "only only" not in text


def test_score_command_error_paths(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _save_roster(home, _roster(_hero(_sands(["501062"]))), "123456789")
    _save_roster(home, _roster(_hero(_sands(["501062"]))), "987654321")
    assert cli.main(["score"]) == 2  # two rosters saved
    err = capsys.readouterr().err
    assert "123456789" in err and "987654321" in err
    profiles = home.parent / "p.toml"
    profiles.write_text(TEXT, encoding="utf-8")
    assert (
        cli.main(["score", "123456789", "--profiles", str(profiles)]) == 0
    )  # the UID filter works
    assert "Test Hero" in capsys.readouterr().out
    for bad in (home.parent / "missing.toml", home.parent / "empty.toml"):
        if bad.name == "empty.toml":
            bad.write_text("", encoding="utf-8")
        assert cli.main(["score", "123456789", "--profiles", str(bad)]) == 1
        out = capsys.readouterr()
        assert (
            out.out == "" and out.err
        )  # nothing is scored against a profile file that cannot be used


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe\x00bad", b"{}"])
def test_a_corrupt_saved_roster_is_a_clean_error(
    home: Path, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    folder = home / "user" / "rosters"
    folder.mkdir(parents=True)
    (folder / "123456789.json").write_bytes(content)
    for command in ("score", "roster"):
        assert cli.main([command]) == 1
        err = capsys.readouterr().err
        assert "Traceback" not in err and "import" in err
