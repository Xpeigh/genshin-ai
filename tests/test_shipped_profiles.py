"""The profile data file we ship must always load: it is hand-edited, so guard it in CI."""

from __future__ import annotations

from pathlib import Path

from genshin_companion.builds.profiles import load_profiles

SHIPPED = Path(__file__).resolve().parent.parent / "profiles" / "characters.toml"


def test_the_shipped_profiles_load_and_are_provisional_or_curated() -> None:
    profiles = load_profiles(SHIPPED.read_text(encoding="utf-8"))
    assert len(profiles) >= 11
    assert {p.confidence for p in profiles} <= {"provisional", "curated"}


def test_guide_profiles_cite_where_they_came_from() -> None:
    profiles = {p.name: p for p in load_profiles(SHIPPED.read_text(encoding="utf-8"))}
    for name in ("Mitya", "Nilou", "Qiqi", "Illuga", "Dahlia", "Chevreuse"):
        p = profiles[name]
        assert p.references, f"{name} has no cited source"
        assert p.substat_tiers and not p.substat_weights
        assert "not the in-game recommendation" in p.source
    # Vesna's profile is the in-game highlight, a different source with a different shape
    assert profiles["Vesna"].substat_weights and "in-game" in profiles["Vesna"].source.lower()
