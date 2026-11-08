"""Inputs and outputs of piece scoring. Pure data: no I/O, no clock, no randomness.

``scoring`` may only import ``scoring`` and ``data`` (enforced by tests/test_architecture.py), so it
cannot read profiles (``builds``) or imported artifacts (``enka``). It defines these small inputs
and the other layers translate into them.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from genshin_companion.data.models import Confidence

Slot = Literal["flower", "plume", "sands", "goblet", "circlet"]
StatId = Annotated[str, Field(pattern=r"^FIGHT_PROP_[A-Z_]+$", max_length=64)]
Text = Annotated[str, Field(min_length=1, max_length=300)]
Weight = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
AffixId = Annotated[str, Field(pattern=r"^[0-9]{1,12}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# -- inputs ----------------------------------------------------------------------------------------


class ArtifactInput(_Frozen):
    """One artifact piece. Only ACTIVATED substat rolls are given, one affix id per roll."""

    slot: Slot
    rarity: int = Field(ge=1, le=5)
    level: int = Field(ge=0, le=20)
    set_name: Text | None
    main_stat: StatId
    roll_affix_ids: list[AffixId] = Field(max_length=16)


class RecommendedMainStat(_Frozen):
    stat: StatId
    usage_percent: float | None = Field(default=None, ge=0, le=100)
    condition: Text | None = None


class RecommendedSet(_Frozen):
    sets: tuple[Text, ...] = Field(min_length=1, max_length=2)
    tier: Literal["best", "alternative"] = "best"
    usage_percent: float | None = Field(default=None, ge=0, le=100)
    condition: Text | None = None


class ScoringProfile(_Frozen):
    """What a character wants, already reduced to numbers by the layer that owns profiles."""

    character_id: Text
    character_name: Text
    kind: Literal["in-game", "guide"]
    source: Text
    observed_at: Text  # ISO date as text: this package never touches clocks or date types
    confidence: Confidence
    weights: dict[StatId, Weight]  # favoured substats; every stat not listed counts as 0
    unscored: dict[StatId, Text]  # conditional stats -> their condition; weight 0 and reported
    main_stats: dict[Slot, list[RecommendedMainStat]]
    sets: tuple[RecommendedSet, ...]
    weights_note: Text | None = None  # e.g. "tier weights are a convention"

    @model_validator(mode="after")
    def _a_stat_is_scored_or_not_scored_never_both(self) -> ScoringProfile:
        both = sorted(set(self.weights) & set(self.unscored))
        if both:
            msg = f"{both} is both weighted and listed as not scored"
            raise ValueError(msg)
        return self


# -- outputs ---------------------------------------------------------------------------------------


class StatBreakdown(_Frozen):
    stat: StatId
    rolls: int
    values: tuple[float, ...]  # the tier values of those rolls, ascending
    weight: float
    contribution: float  # weight x sum of (value / best five-star value)


class NotScored(_Frozen):
    stat: StatId
    condition: Text
    rolls: int


class MainStatFit(_Frozen):
    status: Literal["fixed", "recommended", "conditional", "not_listed", "unknown"]
    usage_percent: float | None = None
    condition: str | None = None


class SetFit(_Frozen):
    status: Literal["best", "alternative", "other"]
    usage_percent: float | None = None
    condition: str | None = None


class Provenance(_Frozen):
    profile_kind: Literal["in-game", "guide"]
    profile_source: str
    profile_observed_at: str
    data_version: str  # the snapshot's game version
    confidence: Confidence  # the weakest of the profile's and the roll data's
    weights_note: str | None = None


class ArtifactScore(_Frozen):
    roll_score: float
    total_rolls: int  # valid rolls only; anything rejected is in ``problems``
    useful_rolls: int  # rolls on stats with a weight above 0
    average_per_roll: float
    stats: tuple[StatBreakdown, ...]  # sorted by stat id
    not_scored: tuple[NotScored, ...]  # conditional stats, sorted by stat id
    crit_value: float  # 2 x CRIT Rate + CRIT DMG, in percent points
    main_stat_fit: MainStatFit
    set_fit: SetFit
    problems: tuple[str, ...]
    provenance: Provenance
