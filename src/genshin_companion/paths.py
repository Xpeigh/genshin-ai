"""Where the app keeps its files, and the "clear all my data" operation.

Layout under the app home (``GENSHIN_COMPANION_HOME`` overrides the per-user default)::

    <home>/.genshin-companion-home   marker file; destructive operations refuse without it
    <home>/user/                     rosters, chat history, settings   (USER DATA)
    <home>/cache/                    HTTP cache, e.g. Enka responses   (USER DATA: contains rosters)
    <home>/logs/                     local logs                        (USER DATA)
    <home>/snapshots/                synced public game data           (not user data)
    <home>/quarantine/               downloaded data awaiting checks   (not user data)

User data never leaves this directory (SPEC.md, "Local-only data").
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

ENV_HOME = "GENSHIN_COMPANION_HOME"
MARKER_NAME = ".genshin-companion-home"


class DataDirError(Exception):
    """The data directory is missing, foreign, or dangerous to modify."""


@dataclass(frozen=True, slots=True)
class DataLayout:
    root: Path

    @property
    def user(self) -> Path:
        return self.root / "user"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def snapshots(self) -> Path:
        return self.root / "snapshots"

    @property
    def quarantine(self) -> Path:
        return self.root / "quarantine"

    @property
    def user_data_dirs(self) -> tuple[Path, ...]:
        return (self.user, self.cache, self.logs)

    @property
    def game_data_dirs(self) -> tuple[Path, ...]:
        return (self.snapshots, self.quarantine)


def resolve_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir("GenshinCompanion", appauthor=False)).resolve()


def _check_safe_root(root: Path) -> Path:
    if str(root) in {"", "."}:
        raise DataDirError("refusing an empty/relative data directory")
    resolved = root.expanduser().resolve()
    if resolved.parent == resolved:
        raise DataDirError("refusing a filesystem root as data directory")
    if resolved == Path.home().resolve():
        raise DataDirError("refusing the user's home directory as data directory")
    return resolved


def ensure_layout(root: Path) -> DataLayout:
    resolved = _check_safe_root(root)
    marker = resolved / MARKER_NAME
    if resolved.exists():
        if not resolved.is_dir():
            raise DataDirError("data directory path is not a directory")
        if not marker.exists() and any(resolved.iterdir()):
            raise DataDirError(
                "directory exists, is not empty and is not a Genshin Companion home; "
                "refusing to use it"
            )
    layout = DataLayout(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    for d in (*layout.user_data_dirs, *layout.game_data_dirs):
        d.mkdir(parents=True, exist_ok=True)
    return layout


def _empty_directory(directory: Path) -> list[Path]:
    """Delete everything inside ``directory`` without following symlinks."""
    removed: list[Path] = []
    for child in directory.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
        removed.append(child)
    return removed


def clear_user_data(layout: DataLayout, *, include_game_data: bool = False) -> list[Path]:
    """Delete UID rosters, chat history, settings, caches and logs. Returns what was removed.

    Game data (snapshots/quarantine) is public and kept unless ``include_game_data`` is set.
    Refuses to run unless the marker file proves this is our own directory.
    """
    root = _check_safe_root(layout.root)
    if not (root / MARKER_NAME).is_file():
        raise DataDirError("marker file missing; refusing to delete anything")
    targets = list(layout.user_data_dirs)
    if include_game_data:
        targets += list(layout.game_data_dirs)
    removed: list[Path] = []
    for directory in targets:
        if directory.is_symlink():  # a symlinked top-level dir: remove the link only
            directory.unlink()
            removed.append(directory)
        if directory.is_dir():
            removed += _empty_directory(directory)
        directory.mkdir(parents=True, exist_ok=True)
    return removed
