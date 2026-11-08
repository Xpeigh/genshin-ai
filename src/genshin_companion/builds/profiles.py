"""Curated per-character stat profiles: the human-in-the-loop part of scoring (SPEC.md decision 4).

A profile says which substats matter for a character and in what order, plus the recommended sets
and main stats. Sources differ: the game's own in-game recommendation (usage statistics from
recently active players) or third-party guide summaries. Both drift over time and mirror what
players do, so every profile records WHEN and HOW it was observed and at which game version.
Profiles start ``provisional``; ``curated`` means Ben approved them; ``verified`` is never set here.

Substat importance is given either as flat ``substat_weights`` (0..1) or as ordered
``substat_tiers`` (best first; one tier holds ties). Tiers are the faithful record of what a source
said. Turning tiers into numbers is the scoring engine's job, with one documented rule, so this
module never invents a weight. A stat may carry a ``condition`` ("only with Favonius Lance"): the
position in the ranking is kept, and the condition is data for the scorer to act on.

Profiles are data (``profiles/*.toml``), loaded from text so this module does no file I/O.
Reference URLs are provenance only; nothing here ever fetches them.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from typing import Annotated, Any, Final, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from genshin_companion.data.models import Confidence, Snapshot

_STAT_RE: Final = re.compile(r"FIGHT_PROP_[A-Z_]+")  # always used with fullmatch
SLOTS: Final = ("sands", "goblet", "circlet")
MAX_TEXT: Final = 300
MAX_STAT_ID: Final = 64
MAX_PROFILES: Final = 500
MAX_SHARE_TOTAL: Final = 100.5  # 100% plus display rounding
MAX_LIST: Final = 20  # tiers, tier entries, choices per slot, sets, weights: far above real use


class ProfileError(Exception):
    """A profile file is malformed."""


def _clean_text(value: str) -> str:
    """Free text is printed to a terminal, so reject control and invisible formatting characters."""
    value = value.strip()
    if not value:
        msg = "must not be blank"
        raise ValueError(msg)
    if not value.isprintable():
        msg = "must not contain control or invisible formatting characters"
        raise ValueError(msg)
    return value


_PRINTABLE = AfterValidator(_clean_text)
Name = Annotated[str, Field(min_length=1, max_length=80), _PRINTABLE]
Role = Annotated[str, Field(min_length=1, max_length=120), _PRINTABLE]
Condition = Annotated[str, Field(min_length=1, max_length=200), _PRINTABLE]
Note = Annotated[str, Field(min_length=1, max_length=MAX_TEXT), _PRINTABLE]


def _plain_number(value: Any) -> Any:
    """Reject booleans and strings before pydantic's lax mode coerces them to numbers."""
    if value is not None and (isinstance(value, bool) or not isinstance(value, int | float)):
        msg = "usage_percent must be a number"
        raise ValueError(msg)
    return value


def _check_https_url(value: str) -> str:
    parts = urlsplit(value)
    if not value.isprintable() or parts.scheme != "https" or not parts.hostname:
        msg = "reference urls must be https with a host"
        raise ValueError(msg)
    if parts.username is not None or parts.password is not None:
        msg = "reference urls must not carry credentials"
        raise ValueError(msg)
    return value


def _check_stat_id(value: str) -> str:
    if len(value) > MAX_STAT_ID or not _STAT_RE.fullmatch(value):
        msg = f"{value[:40]!r} is not a canonical FIGHT_PROP_* stat id"
        raise ValueError(msg)
    return value


class StatChoice(BaseModel):
    """One stat, optionally only recommended under a stated condition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stat: str
    condition: Condition | None = None
    # Share of players who picked this main stat for the slot, as the game shows it (0-100).
    # Only meaningful for main stats; substat tiers must not carry it.
    usage_percent: float | None = Field(default=None, ge=0, le=100)

    @field_validator("stat")
    @classmethod
    def _canonical(cls, value: str) -> str:
        return _check_stat_id(value)

    @field_validator("usage_percent", mode="before")
    @classmethod
    def _number(cls, value: Any) -> Any:
        return _plain_number(value)


def _as_choice(value: Any) -> Any:
    """Allow a bare stat id string in TOML as shorthand for an unconditional choice."""
    return {"stat": value} if isinstance(value, str) else value


Choice = Annotated[StatChoice, BeforeValidator(_as_choice)]


class SetOption(BaseModel):
    """A recommended set: one set (4-piece) or two sets (2-piece + 2-piece)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sets: list[Name] = Field(min_length=1, max_length=2)
    tier: Literal["best", "alternative"] = "best"
    condition: Condition | None = None
    # Share of players using this set, as the game shows it (0-100). Absent when not shown.
    usage_percent: float | None = Field(default=None, ge=0, le=100)

    @field_validator("usage_percent", mode="before")
    @classmethod
    def _a_plain_number(cls, value: Any) -> Any:
        return _plain_number(value)

    @field_validator("sets")
    @classmethod
    def _distinct_names(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            msg = "a 2-piece + 2-piece option needs two different sets"
            raise ValueError(msg)
        return value


class Reference(BaseModel):
    """Where a recommendation came from. The URL is a citation and is never fetched."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    name: Name
    url: str = Field(max_length=MAX_TEXT)

    @field_validator("url")
    @classmethod
    def _plain_https(cls, value: str) -> str:
        return _check_https_url(value)


class WeaponSource(BaseModel):
    """One public page that recommends a weapon: where, when read, how fresh it says it is, rank."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    name: Name
    url: str = Field(max_length=MAX_TEXT)
    accessed: date
    # The page's own statement of how current it is, copied as given: "v7.2", "2026-11-07",
    # "v4.6 (stale)", "undated". Never inferred.
    as_of: Annotated[str, Field(min_length=1, max_length=40), _PRINTABLE]
    rank: int = Field(ge=1, le=50)  # position in that page's ranking, 1 = best

    @field_validator("url")
    @classmethod
    def _plain_https(cls, value: str) -> str:
        return _check_https_url(value)

    @field_validator("rank", mode="before")
    @classmethod
    def _plain_int(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            msg = "rank must be a whole number"
            raise ValueError(msg)
        return value


class WeaponOption(BaseModel):
    """A recommended weapon. Its stats come from the data snapshot, never from this file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Name
    tier: Literal["best", "alternative"] = "best"
    sources: list[WeaponSource] = Field(min_length=1, max_length=10)


class CharacterProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    character_id: str = Field(pattern=r"^[1-9][0-9]*(-[0-9]+)?$", max_length=32)
    name: Name
    role: Role | None = None
    observed_at: date
    game_version: str = Field(pattern=r"^[0-9]{1,2}\.[0-9]{1,2}$")
    source: Annotated[str, Field(min_length=10, max_length=MAX_TEXT), AfterValidator(_clean_text)]
    confidence: Confidence = "provisional"
    # "in-game": the game's own recommendation screen (usage statistics). "guide": third-party
    # guide opinion. A character may have one profile of each kind; scoring prefers in-game.
    kind: Literal["in-game", "guide"] = "in-game"
    recommended_sets: list[SetOption] = Field(default=[], max_length=MAX_LIST)
    recommended_weapons: list[WeaponOption] = Field(default=[], max_length=MAX_LIST)
    # Acceptable main stats per slot (flower and plume are fixed). The list is "as the source
    # lists them", not a ranking; choices with a condition are conditional alternatives.
    recommended_main_stats: dict[
        str, Annotated[list[Choice], Field(min_length=1, max_length=MAX_LIST)]
    ] = {}
    substat_weights: dict[str, float] = {}
    substat_tiers: list[Annotated[list[Choice], Field(max_length=MAX_LIST)]] = Field(
        default=[], max_length=MAX_LIST
    )
    notes: list[Note] = Field(default=[], max_length=MAX_LIST)  # targets and caveats
    references: list[Reference] = Field(default=[], max_length=MAX_LIST)

    @field_validator("confidence")
    @classmethod
    def _never_verified_here(cls, value: Confidence) -> Confidence:
        if value == "verified":
            msg = "'verified' is reserved for hand-checked golden fixtures"
            raise ValueError(msg)
        return value

    @field_validator("substat_weights", mode="before")
    @classmethod
    def _no_booleans(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(isinstance(w, bool) for w in value.values()):
            msg = "a weight must be a number, not true/false"
            raise ValueError(msg)
        return value

    @field_validator("substat_weights")
    @classmethod
    def _weights(cls, value: dict[str, float]) -> dict[str, float]:
        if len(value) > MAX_LIST:
            msg = f"at most {MAX_LIST} weights"
            raise ValueError(msg)
        for stat, weight in value.items():
            _check_stat_id(stat)
            if not 0.0 <= weight <= 1.0:
                msg = f"weight for {stat} must be between 0 and 1"
                raise ValueError(msg)
        if value and not any(w > 0 for w in value.values()):
            msg = "at least one weight must be above 0"
            raise ValueError(msg)
        return value

    @field_validator("substat_tiers")
    @classmethod
    def _tiers(cls, value: list[list[StatChoice]]) -> list[list[StatChoice]]:
        seen: set[str] = set()
        for tier in value:
            if not tier:
                msg = "a substat tier cannot be empty"
                raise ValueError(msg)
            for choice in tier:
                if choice.usage_percent is not None:
                    msg = "substat tiers do not take usage_percent (main stats only)"
                    raise ValueError(msg)
                if choice.stat in seen:
                    msg = f"{choice.stat} appears more than once in substat_tiers"
                    raise ValueError(msg)
                seen.add(choice.stat)
        return value

    @field_validator("recommended_main_stats")
    @classmethod
    def _main_stats(cls, value: dict[str, list[StatChoice]]) -> dict[str, list[StatChoice]]:
        for slot, choices in value.items():
            if slot not in SLOTS:
                msg = f"main stats are only recommended for {SLOTS}, not {slot!r}"
                raise ValueError(msg)
            stats = [c.stat for c in choices]
            if len(set(stats)) != len(stats):
                msg = f"a main stat is listed twice for {slot}"
                raise ValueError(msg)
            # one piece has one main stat, so the shares are exclusive: more than 100% in total
            # (beyond display rounding) can only be a misread or a typo
            total = sum(c.usage_percent or 0.0 for c in choices)
            if total > MAX_SHARE_TOTAL:
                msg = f"usage percentages for {slot} add up to {total:g}%, which is over 100%"
                raise ValueError(msg)
        return value

    @field_validator("recommended_weapons")
    @classmethod
    def _unique_weapons(cls, value: list[WeaponOption]) -> list[WeaponOption]:
        names = [w.name for w in value]
        if len(set(names)) != len(names):
            msg = "a weapon is listed twice"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _one_source_of_truth_for_substats(self) -> CharacterProfile:
        if self.substat_weights and self.substat_tiers:
            msg = "give substat_weights or substat_tiers, not both"
            raise ValueError(msg)
        if not self.substat_weights and not self.substat_tiers:
            msg = "a profile needs substat_weights or substat_tiers"
            raise ValueError(msg)
        return self


def load_profiles(text: str) -> list[CharacterProfile]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"not valid TOML: {exc}") from None
    except RecursionError:
        raise ProfileError("not valid TOML: nested too deeply") from None
    unknown = sorted(set(data) - {"profile"})
    if unknown:
        raise ProfileError(f"unknown top-level key(s) {unknown[:3]}; only [[profile]] is allowed")
    raw = data.get("profile")
    if not isinstance(raw, list) or not raw:
        raise ProfileError("expected at least one [[profile]] table")
    if len(raw) > MAX_PROFILES:
        raise ProfileError(f"too many profiles (limit {MAX_PROFILES})")
    try:
        profiles = [CharacterProfile.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ProfileError(f"invalid profile: {exc.error_count()} problem(s): {exc}") from None
    keys = [(p.character_id, p.kind) for p in profiles]
    if len(keys) != len(set(keys)):
        raise ProfileError("duplicate character_id (per kind) in profiles")
    return profiles


def profile_stats(profile: CharacterProfile) -> set[str]:
    """Every substat id a profile mentions, from weights or tiers."""
    stats = set(profile.substat_weights)
    stats.update(choice.stat for tier in profile.substat_tiers for choice in tier)
    return stats


def validate_profiles(profiles: list[CharacterProfile], snapshot: Snapshot) -> list[str]:
    """Cross-check profiles against the data snapshot. Returns human-readable problems."""
    problems: list[str] = []
    characters = {c.id: c for c in snapshot.characters}
    sets = {s.name for s in snapshot.artifact_sets if s.name}
    substats = {t.stat for t in snapshot.substat_tiers}
    main_stats = {m.stat for m in snapshot.main_stats}
    weapons = {w.name for w in snapshot.weapons if w.name}
    for p in profiles:
        known = characters.get(p.character_id)
        if known is None:
            problems.append(f"{p.name}: character id {p.character_id} is not in the snapshot")
        elif known.name and known.name != p.name:
            problems.append(
                f"{p.name}: id {p.character_id} is {known.name!r} in the snapshot, not {p.name!r}"
            )
        for option in p.recommended_sets:
            for name in option.sets:
                if name not in sets:
                    problems.append(f"{p.name}: set {name!r} is not in the snapshot")
        for weapon in p.recommended_weapons:
            if weapon.name not in weapons:
                problems.append(f"{p.name}: weapon {weapon.name!r} is not in the snapshot")
        for stat in sorted(profile_stats(p)):
            if stat not in substats:
                problems.append(f"{p.name}: {stat} is not a substat that can roll")
        for slot, choices in p.recommended_main_stats.items():
            for choice in choices:
                if choice.stat not in main_stats:
                    problems.append(
                        f"{p.name}: {choice.stat} is not a main stat in the snapshot ({slot})"
                    )
        if p.game_version != snapshot.game_version:
            problems.append(
                f"{p.name}: profile read at game {p.game_version} but data is "
                f"{snapshot.game_version}; recommendations drift, re-check in game"
            )
    return problems
