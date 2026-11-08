from __future__ import annotations

import pytest

from genshin_companion.data.changelog import diff, render
from genshin_companion.data.models import Snapshot, SubstatTier
from genshin_companion.data.validate import validate
from helpers import snapshot


def with_tiers(snap: Snapshot, tiers: list[SubstatTier]) -> Snapshot:
    return snap.model_copy(update={"substat_tiers": tiers})


def test_good_first_snapshot_is_ok() -> None:
    report = validate(snapshot(), None)
    assert report.status == "ok", report
    assert not report.errors


def test_empty_datasets_are_rejected() -> None:
    for field in ("substat_tiers", "main_stats", "characters", "weapons", "artifact_sets"):
        report = validate(snapshot().model_copy(update={field: []}), None)
        assert report.status == "rejected", field
        assert any(field in e for e in report.errors)


def test_main_stat_must_not_decrease_with_level() -> None:
    snap = snapshot()
    broken = [
        m.model_copy(update={"value": 1.0}) if (m.stat == "FIGHT_PROP_HP" and m.level == 1) else m
        for m in snap.main_stats
    ]
    report = validate(snap.model_copy(update={"main_stats": broken}), None)
    assert report.status == "rejected"
    assert any("decrease" in e for e in report.errors)


def test_duplicate_ids_are_rejected() -> None:
    snap = snapshot()
    report = validate(snap.model_copy(update={"characters": snap.characters * 2}), None)
    assert report.status == "rejected"


def test_unchanged_snapshot_has_no_diff_and_is_ok() -> None:
    report = validate(snapshot(), snapshot())
    assert report.status == "ok"
    assert not diff(snapshot(), snapshot()).has_changes


def test_changed_substat_roll_value_is_held_for_review() -> None:
    old = snapshot()
    new_tiers = [
        t.model_copy(update={"value": t.value * 1.5}) if t.stat == "FIGHT_PROP_HP" else t
        for t in old.substat_tiers
    ]
    report = validate(with_tiers(old, new_tiers), old)
    assert report.status == "held"
    assert any("roll" in r for r in report.review_reasons)


def test_removing_most_characters_is_held() -> None:
    old = snapshot()
    many = old.model_copy(
        update={
            "characters": [
                old.characters[0].model_copy(update={"id": str(1000 + i)}) for i in range(10)
            ]
        }
    )
    shrunk = many.model_copy(update={"characters": many.characters[:3]})
    report = validate(shrunk, many)
    assert report.status == "held"


def test_game_version_going_backwards_is_held() -> None:
    old = snapshot()
    older = old.model_copy(update={"game_version": "7.1"})
    assert validate(older, old).status == "held"


def test_unknown_version_after_known_is_held() -> None:
    old = snapshot()
    assert validate(old.model_copy(update={"game_version": "unknown"}), old).status == "held"


def test_confidence_downgrade_is_reported_as_a_warning() -> None:
    old = snapshot()
    new = old.model_copy(update={"confidence": {**old.confidence, "substat_tiers": "provisional"}})
    report = validate(new, old)
    assert any("confidence" in w for w in report.warnings)


def test_changelog_lists_added_removed_and_changed() -> None:
    old = snapshot()
    extra = old.characters[0].model_copy(update={"id": "10000999", "name": "New Hero"})
    changed_weapon = old.weapons[0].model_copy(update={"rarity": 4})
    new = old.model_copy(
        update={
            "characters": [*old.characters, extra],
            "weapons": [changed_weapon],
            "game_version": "7.3",
        }
    )
    cl = diff(old, new)
    assert cl.has_changes
    text = render(cl)
    assert "7.2" in text and "7.3" in text
    assert "New Hero" in text and "10000999" in text
    assert "11501" in text  # changed weapon


def _renamed(snap, dataset: str, name: str):  # type: ignore[no-untyped-def]
    items = [
        getattr(snap, dataset)[0].model_copy(update={"name": name}),
        *getattr(snap, dataset)[1:],
    ]
    return snap.model_copy(update={dataset: items})


@pytest.mark.parametrize("dataset", ["characters", "weapons", "artifact_sets"])
@pytest.mark.parametrize(
    "bad", ["", "   ", "Hero\x1b[2J", "bell\x07", "tab\there", "x" * 200, "line\nbreak"]
)
def test_unusable_names_are_rejected(dataset: str, bad: str) -> None:
    report = validate(_renamed(snapshot(), dataset, bad), None)
    assert report.status == "rejected", (dataset, repr(bad))
    assert any("name" in e and dataset in e for e in report.errors)


@pytest.mark.parametrize("dataset", ["characters", "weapons", "artifact_sets"])
def test_a_missing_name_is_allowed_and_an_ordinary_name_is_fine(dataset: str) -> None:
    items = [getattr(snapshot(), dataset)[0].model_copy(update={"name": None})]
    assert validate(snapshot().model_copy(update={dataset: items}), None).status == "ok"
    assert validate(_renamed(snapshot(), dataset, "Ordinary Name's é"), None).status == "ok"
