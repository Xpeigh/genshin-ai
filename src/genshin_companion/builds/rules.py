"""Curated game rules the data snapshot does not carry (today: the maximum level of each rarity).

Loaded from text so this module does no file I/O. The file is data, hand-curated with provenance
like the profiles: where each number came from, when, and how sure we are. ``verified`` is never
set here.
"""

from __future__ import annotations

import tomllib
from typing import Any, Final

from pydantic import ValidationError

from genshin_companion.scoring import ArtifactRules

_ALLOWED: Final = {"confidence", "observed_at", "source", "notes", "max_level"}


class RulesError(Exception):
    """A rules file is malformed."""


def load_artifact_rules(text: str) -> ArtifactRules:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RulesError(f"not valid TOML: {exc}") from None
    except (RecursionError, ValueError):
        raise RulesError("not valid TOML: a value is out of range or nested too deeply") from None
    unknown = sorted(set(data) - _ALLOWED)
    if unknown:
        raise RulesError(f"unknown key(s) {unknown[:3]}")
    raw_levels: Any = data.get("max_level")
    if not isinstance(raw_levels, dict) or not raw_levels:
        raise RulesError("expected a [max_level] table with one entry per rarity")
    levels: dict[int, int] = {}
    for key, level in raw_levels.items():
        if not key.isdigit() or isinstance(level, bool) or not isinstance(level, int):
            raise RulesError("[max_level] needs rarity numbers as keys and whole numbers as values")
        levels[int(key)] = level
    if data.get("confidence") == "verified":
        raise RulesError("'verified' is reserved for hand-checked golden fixtures")
    try:
        return ArtifactRules.model_validate(
            {
                "max_level": levels,
                "confidence": data.get("confidence"),
                "source": data.get("source"),
                "observed_at": data.get("observed_at"),
                "notes": tuple(data.get("notes", ())),
            }
        )
    except ValidationError as exc:
        raise RulesError(f"invalid rules: {exc.error_count()} problem(s)") from None
