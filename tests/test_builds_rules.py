from __future__ import annotations

from pathlib import Path

import pytest

from genshin_companion.builds.rules import RulesError, load_artifact_rules

GOOD = """
confidence = "provisional"
observed_at = "2026-11-09"
source = "a test source with enough detail to be a real citation"
notes = ["2-star unconfirmed"]

[max_level]
1 = 4
2 = 4
3 = 12
4 = 16
5 = 20
"""
SHIPPED = Path(__file__).resolve().parent.parent / "rules" / "artifact-levels.toml"


def test_a_good_file_loads_with_its_provenance() -> None:
    rules = load_artifact_rules(GOOD)
    assert rules.max_level == {1: 4, 2: 4, 3: 12, 4: 16, 5: 20}
    assert rules.confidence == "provisional" and rules.observed_at == "2026-11-09"
    assert rules.notes == ("2-star unconfirmed",)


@pytest.mark.parametrize(
    "bad",
    [
        GOOD.replace('confidence = "provisional"', 'confidence = "verified"'),  # reserved
        GOOD.replace("5 = 20", "5 = 21"),  # not a multiple of 4
        GOOD.replace("5 = 20", "5 = 24"),  # above the cap
        GOOD.replace("1 = 4", "6 = 20"),  # no such rarity
        GOOD.replace("3 = 12", "3 = 4").replace(
            "2 = 4", "2 = 8"
        ),  # a higher rarity with fewer levels
        GOOD.replace("5 = 20", "5 = true"),  # a boolean is not a level
        GOOD.replace("5 = 20", '5 = "20"'),
        GOOD.replace('source = "a test source with enough detail to be a real citation"\n', ""),
        GOOD.replace("[max_level]", "extra = 1\n[max_level]"),  # unknown key
        GOOD.replace("[max_level]", "[levels]"),  # wrong table
        GOOD.replace("1 = 4\n", "one = 4\n"),
        "not toml [[[",
        "a = " + "[" * 50_000 + "]" * 50_000,
        "",
    ],
)
def test_bad_files_are_rejected_cleanly(bad: str) -> None:
    with pytest.raises(RulesError):
        load_artifact_rules(bad)


def test_the_shipped_rules_load_and_say_where_they_came_from() -> None:
    rules = load_artifact_rules(SHIPPED.read_text(encoding="utf-8"))
    assert rules.max_level[5] == 20  # the one level Ben already knew
    assert set(rules.max_level) == {1, 2, 3, 4, 5}
    assert "Genshin Optimizer" in rules.source and rules.confidence in {"provisional", "curated"}
    assert any("2-star" in n for n in rules.notes)  # the open question is recorded, not hidden
