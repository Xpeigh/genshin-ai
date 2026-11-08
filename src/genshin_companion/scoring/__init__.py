"""Pure, deterministic scoring (no network, no LLM, no file I/O). See docs/scoring-spec.md."""

from genshin_companion.scoring.artifact import score_artifact
from genshin_companion.scoring.character import CharacterSummary, summarize_character
from genshin_companion.scoring.models import (
    ArtifactInput,
    ArtifactScore,
    MainStatFit,
    NotScored,
    Provenance,
    RecommendedMainStat,
    RecommendedSet,
    ScoringProfile,
    SetFit,
    StatBreakdown,
)

__all__ = [
    "ArtifactInput",
    "ArtifactScore",
    "CharacterSummary",
    "MainStatFit",
    "NotScored",
    "Provenance",
    "RecommendedMainStat",
    "RecommendedSet",
    "ScoringProfile",
    "SetFit",
    "StatBreakdown",
    "score_artifact",
    "summarize_character",
]
