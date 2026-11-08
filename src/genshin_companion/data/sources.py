"""Where game data is downloaded from. Hosts used here must be in ``config.DEFAULT_ALLOWED_HOSTS``.

See docs/data-sources.md for licences/terms. Enka's store files have NO licence, so they are only
ever fetched at runtime into the user's own data directory, never committed or redistributed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Commit of EnkaNetwork/API-docs resolved with `git ls-remote ... refs/heads/master` on 2026-11-08.
# Bump deliberately (and read the data changelog); "latest" is an explicit opt-in (--latest).
ENKA_PINNED_REF: Final = "b94bc40528941126590e0eefb0f03278e7a44ec8"
_ENKA_RAW: Final = "https://raw.githubusercontent.com/EnkaNetwork/API-docs"
_AMBER: Final = "https://gi.yatta.moe/api/v2/static"
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class SourceFile:
    source: str  # "enka" | "amber"
    name: str  # key used by data.normalize (ENKA_FILES / AMBER_FILES)
    url: str
    max_bytes: int


def is_pinned(ref: str) -> bool:
    return bool(_SHA.match(ref))


def enka_files(ref: str) -> list[SourceFile]:
    if not (is_pinned(ref) or ref == "master"):
        raise ValueError("ref must be a 40-hex commit SHA or the literal 'master'")
    base = f"{_ENKA_RAW}/{ref}/store"
    mb = 1024 * 1024
    return [
        SourceFile("enka", "affixes", f"{base}/gi/affixes.json", 2 * mb),
        SourceFile("enka", "affixes_legacy", f"{base}/affixes.json", 2 * mb),
        SourceFile("enka", "relic_levels", f"{base}/gi/relic_levels.json", 2 * mb),
        SourceFile("enka", "avatars", f"{base}/gi/avatars.json", 8 * mb),
        SourceFile("enka", "weapons", f"{base}/gi/weapons.json", 8 * mb),
        SourceFile("enka", "relics", f"{base}/gi/relics.json", 16 * mb),
        SourceFile("enka", "locs", f"{base}/gi/locs.json", 16 * mb),
    ]


def amber_files() -> list[SourceFile]:
    mb = 1024 * 1024
    return [
        SourceFile("amber", "reliquaryCurve", f"{_AMBER}/reliquaryCurve", 4 * mb),
        SourceFile("amber", "changelog", f"{_AMBER}/changelog", 4 * mb),
    ]
