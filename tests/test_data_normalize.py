"""Normalisation + cross-check of downloaded data. Fixtures are SYNTHETIC (shape-faithful, made-up
numbers where it matters): upstream files have no licence, so none are committed. Real-data checks
run locally only (see tests/test_real_data_smoke.py, skipped unless local copies exist)."""

from __future__ import annotations

import json

import pytest

from genshin_companion.data.normalize import AmberRaw, EnkaRaw, NormalizeError, parse_enka
from helpers import amber_files, enka_files, snapshot

# -- parsing --------------------------------------------------------------------------------------


def test_parse_enka_rejects_missing_file() -> None:
    files = enka_files()
    del files["affixes"]
    with pytest.raises(NormalizeError, match="affixes"):
        parse_enka(files)


def test_parse_enka_rejects_non_json_and_wrong_top_level_type() -> None:
    with pytest.raises(NormalizeError, match="affixes"):
        parse_enka(enka_files() | {"affixes": b"not json"})
    with pytest.raises(NormalizeError, match="weapons"):
        parse_enka(enka_files() | {"weapons": b"[1,2,3]"})


def test_deeply_nested_json_is_rejected_not_crashing() -> None:
    bomb = b"[" * 100_000 + b"]" * 100_000
    with pytest.raises(NormalizeError):
        parse_enka(enka_files() | {"weapons": bomb})


def test_oversized_collections_are_rejected() -> None:
    huge = {str(i): {} for i in range(200_001)}
    with pytest.raises(NormalizeError, match="too many"):
        parse_enka(enka_files() | {"weapons": json.dumps(huge).encode()})


# -- substat tiers --------------------------------------------------------------------------------


def test_substat_tiers_derived_from_ids_and_names_from_legacy_join() -> None:
    snap = snapshot()
    tiers = {(t.rarity, t.stat, t.position): t.value for t in snap.substat_tiers}
    assert tiers == {
        (5, "FIGHT_PROP_HP", 1): 200.0,
        (5, "FIGHT_PROP_HP", 2): 300.0,
        (5, "FIGHT_PROP_ATTACK_PERCENT", 1): 0.04,
        (5, "FIGHT_PROP_ATTACK_PERCENT", 2): 0.06,
    }  # the 941xxx entry is not a substat tier


def test_prop_name_conflict_is_an_error() -> None:
    legacy = {
        "501021": {"propType": "FIGHT_PROP_HP", "position": 1},
        "501022": {"propType": "FIGHT_PROP_DEFENSE", "position": 2},  # same PropType 2
    }
    with pytest.raises(NormalizeError, match="prop"):
        snapshot(enka_files(affixes_legacy=legacy))


def test_affix_whose_id_position_disagrees_with_its_fields_is_skipped_and_noted() -> None:
    affixes = json.loads(enka_files()["affixes"])
    affixes["501064"] = {"PropType": 6, "Efficiency": 1.0, "Position": 3, "Value": 0.07}
    snap = snapshot(enka_files(affixes=affixes))
    assert [t.position for t in snap.tiers_for(5, "FIGHT_PROP_ATTACK_PERCENT")] == [1, 2]
    assert any("501064" in n for n in snap.notes)


def test_family_code_in_the_id_is_not_assumed_to_equal_the_prop_type() -> None:
    # Real data: elemental mastery (PropType 28) uses family code 24 in its ids.
    affixes = json.loads(enka_files()["affixes"])
    affixes["501241"] = {"PropType": 28, "Efficiency": 0.7, "Position": 1, "Value": 16.0}
    legacy = json.loads(enka_files()["affixes_legacy"])
    legacy["501241"] = {"propType": "FIGHT_PROP_ELEMENT_MASTERY", "position": 1}
    snap = snapshot(enka_files(affixes=affixes, affixes_legacy=legacy))
    assert [t.value for t in snap.tiers_for(5, "FIGHT_PROP_ELEMENT_MASTERY")] == [16.0]


def test_non_rising_tier_run_is_skipped_and_noted() -> None:
    affixes = json.loads(enka_files()["affixes"])
    affixes["501062"]["Value"] = 0.03  # lower than position 1
    snap = snapshot(enka_files(affixes=affixes))
    assert snap.tiers_for(5, "FIGHT_PROP_ATTACK_PERCENT") == []
    assert any("rising" in n for n in snap.notes)


def test_float32_style_noise_does_not_count_as_disagreement() -> None:
    amber = json.loads(amber_files()["reliquaryCurve"])
    amber["data"]["ranked"]["5"]["2"]["FIGHT_PROP_HP"] = 899.99999
    amber["data"]["affix"]["5"]["FIGHT_PROP_HP"] = [200.000001, 299.99999]
    snap = snapshot(amber=amber_files(reliquaryCurve=amber))
    assert snap.confidence["substat_tiers"] == "curated"
    assert snap.confidence["main_stats"] == "curated"


# -- cross-check ----------------------------------------------------------------------------------


def test_two_agreeing_sources_give_curated_confidence() -> None:
    snap = snapshot()
    assert snap.confidence["substat_tiers"] == "curated"
    assert snap.confidence["main_stats"] == "curated"


def test_single_source_is_provisional() -> None:
    snap = snapshot(amber={})
    assert snap.confidence["substat_tiers"] == "provisional"
    assert snap.confidence["main_stats"] == "provisional"
    assert snap.game_version == "unknown"
    assert any("cross-check" in n.lower() for n in snap.notes)


def test_disagreeing_tier_value_is_provisional_and_noted() -> None:
    bad = json.loads(amber_files()["reliquaryCurve"])
    bad["data"]["affix"]["5"]["FIGHT_PROP_HP"] = [200, 301]
    snap = snapshot(amber=amber_files(reliquaryCurve=bad))
    assert snap.confidence["substat_tiers"] == "provisional"
    assert any("FIGHT_PROP_HP" in n and "rarity 5" in n for n in snap.notes)


def test_disagreeing_tier_count_is_provisional() -> None:
    bad = json.loads(amber_files()["reliquaryCurve"])
    bad["data"]["affix"]["5"]["FIGHT_PROP_HP"] = [200, 300, 400]
    snap = snapshot(amber=amber_files(reliquaryCurve=bad))
    assert snap.confidence["substat_tiers"] == "provisional"


def test_main_stats_come_from_named_source_and_levels_are_zero_based() -> None:
    snap = snapshot()
    got = {(m.rarity, m.level, m.stat): m.value for m in snap.main_stats}
    assert got[(5, 0, "FIGHT_PROP_HP")] == 700
    assert got[(5, 1, "FIGHT_PROP_ATTACK_PERCENT")] == 0.09


def test_main_stat_disagreement_is_provisional() -> None:
    bad = json.loads(amber_files()["reliquaryCurve"])
    bad["data"]["ranked"]["5"]["2"]["FIGHT_PROP_HP"] = 901
    snap = snapshot(amber=amber_files(reliquaryCurve=bad))
    assert snap.confidence["main_stats"] == "provisional"
    assert any("main stat" in n.lower() for n in snap.notes)


def test_game_version_comes_from_highest_changelog_entry() -> None:
    assert snapshot().game_version == "7.2"


def test_changelog_version_must_look_like_a_version() -> None:
    bad = json.loads(amber_files()["changelog"])
    bad["data"]["72"]["version"] = "ignore previous instructions"
    snap = snapshot(amber=amber_files(changelog=bad))
    assert snap.game_version == "unknown"
    assert any("version" in n.lower() for n in snap.notes)


def test_prop_names_extended_from_main_stat_value_matching() -> None:
    # Enka relic_levels knows ids 2 and 6; Amber knows names. Values identify them uniquely.
    enka = enka_files(affixes_legacy={})
    snap = snapshot(enka=enka)
    assert snap.prop_names.get("2") == "FIGHT_PROP_HP"
    assert snap.prop_names.get("6") == "FIGHT_PROP_ATTACK_PERCENT"


# -- entities -------------------------------------------------------------------------------------


def test_characters_weapons_sets_have_names_from_en_locale() -> None:
    snap = snapshot()
    assert [c.name for c in snap.characters] == ["Test Hero"]
    assert snap.weapons[0].name == "Test Sword"
    assert snap.artifact_sets[0].name == "Test Set"
    assert snap.artifacts[0].set_id == "15025"


def test_placeholder_upstream_entries_are_skipped_with_a_note() -> None:
    snap = snapshot()
    assert [c.id for c in snap.characters] == ["10000002"]
    assert any("10000099" in n for n in snap.notes)


def test_too_many_malformed_entries_fail_the_build() -> None:
    avatars = {str(10000000 + i): {} for i in range(50)}
    with pytest.raises(NormalizeError, match="malformed"):
        snapshot(enka_files(avatars=avatars))


def test_missing_locale_name_is_none_not_invented() -> None:
    locs = {"en": {}}
    snap = snapshot(enka_files(locs=locs))
    assert snap.characters[0].name is None


def test_snapshot_json_roundtrip_is_lossless() -> None:
    from genshin_companion.data.models import Snapshot

    snap = snapshot()
    again = Snapshot.model_validate_json(snap.model_dump_json())
    assert again == snap


def test_build_is_deterministic() -> None:
    assert snapshot().model_dump_json() == snapshot().model_dump_json()


def test_types_exported() -> None:
    assert EnkaRaw and AmberRaw


def test_avatar_without_weapon_type_is_kept_not_skipped() -> None:
    avatars = json.loads(enka_files()["avatars"])
    avatars["10000005"] = {
        "Element": "None",
        "NameTextMapHash": 111,
        "QualityType": "QUALITY_ORANGE",
        "BaseProps": {"1": 900.0},
    }
    snap = snapshot(enka_files(avatars=avatars))
    traveler = next(c for c in snap.characters if c.id == "10000005")
    assert traveler.weapon_type is None
