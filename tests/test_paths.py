from __future__ import annotations

import os
from pathlib import Path

import pytest

from genshin_companion.paths import (
    ENV_HOME,
    MARKER_NAME,
    DataDirError,
    clear_user_data,
    ensure_layout,
    resolve_home,
)


def populate(root: Path) -> dict[str, Path]:
    layout = ensure_layout(root)
    files = {
        "roster": layout.user / "rosters" / "800123456.json",
        "chat": layout.user / "chat" / "history.jsonl",
        "cache": layout.cache / "enka" / "abc.json",
        "log": layout.logs / "app.log",
        "snapshot": layout.snapshots / "2026-11-01" / "characters.json",
        "quarantine": layout.quarantine / "incoming" / "x.json",
    }
    for p in files.values():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("data", encoding="utf-8")
    return files


def test_env_var_overrides_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "h"))
    assert resolve_home() == (tmp_path / "h").resolve()


def test_default_home_is_per_user_and_not_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_HOME, raising=False)
    home = resolve_home()
    assert home.is_absolute()
    assert "genshin" in home.name.lower() or "genshin" in str(home).lower()


def test_ensure_layout_creates_dirs_and_marker(tmp_path: Path) -> None:
    layout = ensure_layout(tmp_path / "home")
    for d in (layout.user, layout.cache, layout.logs, layout.snapshots, layout.quarantine):
        assert d.is_dir()
    assert (layout.root / MARKER_NAME).is_file()


def test_ensure_layout_refuses_a_non_empty_foreign_directory(tmp_path: Path) -> None:
    foreign = tmp_path / "Documents"
    foreign.mkdir()
    (foreign / "thesis.docx").write_text("precious")
    with pytest.raises(DataDirError):
        ensure_layout(foreign)


def test_clear_user_data_removes_user_cache_logs_but_keeps_game_data(tmp_path: Path) -> None:
    files = populate(tmp_path / "home")
    removed = clear_user_data(ensure_layout(tmp_path / "home"))
    for key in ("roster", "chat", "cache", "log"):
        assert not files[key].exists(), key
    assert files["snapshot"].exists()
    assert files["quarantine"].exists()
    assert removed  # reports what it did


def test_clear_can_include_game_data(tmp_path: Path) -> None:
    files = populate(tmp_path / "home")
    clear_user_data(ensure_layout(tmp_path / "home"), include_game_data=True)
    assert not any(p.exists() for p in files.values())
    assert (tmp_path / "home" / MARKER_NAME).exists()  # still a valid home afterwards


def test_clear_is_idempotent_and_recreates_empty_dirs(tmp_path: Path) -> None:
    populate(tmp_path / "home")
    layout = ensure_layout(tmp_path / "home")
    clear_user_data(layout)
    clear_user_data(layout)
    assert layout.user.is_dir()
    assert not any(layout.user.iterdir())


def test_clear_refuses_without_marker(tmp_path: Path) -> None:
    layout = ensure_layout(tmp_path / "home")
    (layout.root / MARKER_NAME).unlink()
    (layout.user / "keep.txt").write_text("x")
    with pytest.raises(DataDirError):
        clear_user_data(layout)
    assert (layout.user / "keep.txt").exists()


def test_clear_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep me")
    layout = ensure_layout(tmp_path / "home")
    link = layout.user / "link"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    clear_user_data(layout)
    assert (outside / "precious.txt").exists()
    assert not link.exists() and not link.is_symlink()


@pytest.mark.parametrize("bad", ["", "/", "C:\\"])
def test_dangerous_roots_are_refused(bad: str) -> None:
    with pytest.raises(DataDirError):
        ensure_layout(Path(bad) if bad else Path(""))
