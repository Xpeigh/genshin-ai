from __future__ import annotations

from pathlib import Path

import pytest

from genshin_companion.app.cli import main
from genshin_companion.app.report import render_profile
from genshin_companion.builds.profiles import load_profiles
from genshin_companion.paths import ensure_layout
from test_builds_profiles import GOOD, WEIGHTS


def _render(text: str) -> str:
    (p,) = load_profiles(text)
    return render_profile(p)


def test_tiers_render_best_first_with_conditions_visible() -> None:
    out = _render(GOOD)
    assert "Test Hero (10000002) [provisional] read 2026-11-08 at game 7.2" in out
    assert "ATK% > HP (only with a test weapon)" in out


def test_ties_within_a_tier_are_joined_with_a_slash() -> None:
    text = GOOD.replace(
        '["FIGHT_PROP_ATTACK_PERCENT"],\n    [{',
        '["FIGHT_PROP_ATTACK_PERCENT", "FIGHT_PROP_CRITICAL"],\n    [{',
    )
    assert "ATK% / CRIT Rate > HP (only with a test weapon)" in _render(text)


def test_main_stats_sets_and_references_are_shown_with_conditions() -> None:
    out = _render(GOOD)
    assert "circlet: ATK%, HP (only at C6)" in out
    assert "Test Set (best)" in out
    assert "Test Set + Test Set Two (alternative: if nobody else uses the first set)" in out
    assert "Test Guide" in out and "ER target about 120%" in out


def test_weights_profile_renders_its_weights() -> None:
    out = _render(WEIGHTS)
    assert "ATK%=1" in out and "HP=0.5" in out
    assert "(not recorded)" in out  # no sets or main stats


def test_profiles_command_prints_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(tmp_path / "home"))
    ensure_layout(tmp_path / "home")
    f = tmp_path / "p.toml"
    f.write_text(GOOD.replace(', "Test Set Two"', ""), encoding="utf-8")
    assert main(["profiles", "--file", str(f)]) == 0
    out = capsys.readouterr().out
    assert "Test Hero" in out and "substats:" in out
    assert "No data snapshot" in out  # nothing synced in the temp home


def test_profiles_command_reports_a_bad_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(tmp_path / "home"))
    f = tmp_path / "p.toml"
    f.write_text("not toml [[[", encoding="utf-8")
    assert main(["profiles", "--file", str(f)]) == 1
    assert "invalid" in capsys.readouterr().err


def test_profiles_command_survives_unreadable_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(tmp_path / "home"))
    latin = tmp_path / "latin.toml"
    latin.write_bytes(b'name = "\xe9"')
    assert main(["profiles", "--file", str(latin)]) == 1
    assert main(["profiles", "--file", str(tmp_path)]) == 1  # a directory
    big = tmp_path / "big.toml"
    big.write_text("# " + "x" * 2_000_000, encoding="utf-8")
    assert main(["profiles", "--file", str(big)]) == 1
    err = capsys.readouterr().err
    assert err.count("Traceback") == 0 and "too large" in err
