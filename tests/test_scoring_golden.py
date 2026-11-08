"""Golden tests on Ben's own pieces (tests/fixtures/golden_artifacts.json, copied from the game UI).

They need the REAL data snapshot (upstream files are unlicensed, so it is never committed): set
GENSHIN_REAL_SNAPSHOT to a snapshot.json path. ``tasks.py check`` sets it automatically when the
repo-local ``data-home`` holds a synced snapshot; otherwise these tests are skipped.

No expected value is invented. Everything is read off the displayed numbers:
- the roll score of a piece is linear in the displayed totals, so for each favoured stat it must
  equal weight x (displayed total / best five-star roll), an independent route to the engine's
  per-roll arithmetic;
- the roll and useful-roll counts below are plain counts from the substats Ben typed in.
"""

from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

import pytest

from genshin_companion.builds.profiles import CharacterProfile, load_profiles
from genshin_companion.builds.scoring_profile import select_profile, to_scoring_profile
from genshin_companion.data.models import Snapshot
from genshin_companion.scoring import ArtifactInput, score_artifact

_SNAPSHOT = os.environ.get("GENSHIN_REAL_SNAPSHOT")
pytestmark = pytest.mark.skipif(not _SNAPSHOT, reason="set GENSHIN_REAL_SNAPSHOT to run")

ROOT = Path(__file__).resolve().parent.parent
PIECES = json.loads(
    (Path(__file__).parent / "fixtures" / "golden_artifacts.json").read_text(encoding="utf-8")
)["pieces"]
FLAT = {"FIGHT_PROP_HP", "FIGHT_PROP_ATTACK", "FIGHT_PROP_DEFENSE", "FIGHT_PROP_ELEMENT_MASTERY"}
PROFILE_NAME = {"Traveller (Cryo)": "Traveler"}  # the game's spelling vs the snapshot's
# the Traveler has one snapshot id per element; Ben's is the Cryo one
CHAR_ID_OVERRIDE = {"Traveler": "10000007-705"}


def _char_ids(snap: Snapshot) -> dict[str, str]:
    ids = {c.name: c.id for c in snap.characters}
    ids.update(CHAR_ID_OVERRIDE)
    return ids


@pytest.fixture(scope="module")
def snap() -> Snapshot:
    assert _SNAPSHOT
    return Snapshot.model_validate_json(Path(_SNAPSHOT).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def profiles() -> list[CharacterProfile]:
    return load_profiles((ROOT / "profiles" / "characters.toml").read_text(encoding="utf-8"))


def _best_five(snap: Snapshot, stat: str) -> float:
    return max(t.value for t in snap.substat_tiers if t.rarity == 5 and t.stat == stat)


def _decompose(snap: Snapshot, stat: str, shown: float) -> dict[int, list[tuple[float, ...]]]:
    """Every way to build the displayed total from five-star rolls, keyed by roll count."""
    tol = 0.5 if stat in FLAT else 0.0006
    values = sorted(t.value for t in snap.substat_tiers if t.rarity == 5 and t.stat == stat)
    found: dict[int, list[tuple[float, ...]]] = {}
    for n in range(1, 7):
        hits = [
            c
            for c in itertools.combinations_with_replacement(values, n)
            if abs(sum(c) - shown) <= tol
        ]
        if hits:
            found[n] = hits
    return found


def _rolls(snap: Snapshot, piece: dict) -> tuple[list[str], dict[str, int]]:  # type: ignore[type-arg]
    ids = {(t.stat, t.value): t.affix_id for t in snap.substat_tiers if t.rarity == 5}
    out: list[str] = []
    per_stat: dict[str, int] = {}
    for sub in piece["substats"]:
        if not sub["active"]:
            continue
        options = _decompose(snap, sub["stat"], sub["value"])
        assert len(options) == 1, (
            f"{piece['piece_name']} {sub['stat']}: roll count is ambiguous {sorted(options)}"
        )
        ((n, combos),) = options.items()
        out += [ids[(sub["stat"], v)] for v in combos[0]]
        per_stat[sub["stat"]] = n
    return out, per_stat


def test_main_stats_match_the_snapshot_at_that_level(snap: Snapshot) -> None:
    table = {(m.rarity, m.level, m.stat): m.value for m in snap.main_stats}
    for p in PIECES:
        want = table[(5, p["level"], p["main_stat"])]
        assert p["main_value"] == pytest.approx(want, rel=0.01), p["piece_name"]


def test_every_displayed_substat_splits_into_a_whole_number_of_rolls(snap: Snapshot) -> None:
    for p in PIECES:
        _rolls(snap, p)  # asserts a unique roll count per stat


@pytest.mark.parametrize(
    "piece", PIECES, ids=lambda p: f"{p['equipped_by']}-{p['slot']}-{p['level']}"
)
def test_roll_score_equals_weight_times_displayed_total_over_best_roll(
    piece: dict,
    snap: Snapshot,
    profiles: list[CharacterProfile],  # type: ignore[type-arg]
) -> None:
    holder = PROFILE_NAME.get(piece["equipped_by"], piece["equipped_by"])
    chars = _char_ids(snap)
    if piece["equipped_by"] == "No one":
        pytest.skip("this piece is not equipped by anyone, so there is no profile to score it with")
    assert holder in chars, f"{holder} is not in the snapshot: the golden test would silently skip"
    chosen = select_profile(profiles, chars[holder])
    assert chosen is not None, holder
    sp = to_scoring_profile(chosen)
    ids, _ = _rolls(snap, piece)
    art = ArtifactInput(
        slot=piece["slot"],
        rarity=5,
        level=piece["level"],
        set_name=None,
        main_stat=piece["main_stat"],
        roll_affix_ids=ids,
    )
    got = score_artifact(art, sp, snap)
    assert got.problems == ()
    expected = sum(
        sp.weights.get(s["stat"], 0.0) * s["value"] / _best_five(snap, s["stat"])
        for s in piece["substats"]
        if s["active"]
    )
    # displayed values are rounded to the game's display precision, hence the small tolerance
    assert got.roll_score == pytest.approx(expected, abs=0.02 * max(1, got.total_rolls))


# Plain counts read off the substats Ben typed in (active substats only), checked against the
# in-game profile's favoured stats: (character, slot, level) -> (rolls, rolls on favoured stats).
COUNTS = {
    ("Diluc", "sands", 4): (4, 3),  # CRIT DMG, ATK%, EM are favoured; HP is not
    ("Diluc", "goblet", 4): (4, 1),  # only CRIT DMG is favoured (ATK flat, HP flat, ER are not)
    ("Vesna", "sands", 20): (8, 0),  # HP x4, DEF x2, ATK, ER: none favoured for Vesna
    ("Xinyan", "flower", 0): (4, 3),  # CRIT DMG, ER, CRIT Rate favoured; flat ATK is not
}


@pytest.mark.parametrize(("key", "expected"), sorted(COUNTS.items()))
def test_roll_and_useful_roll_counts(
    key: tuple[str, str, int],
    expected: tuple[int, int],
    snap: Snapshot,
    profiles: list[CharacterProfile],
) -> None:
    who, slot, level = key
    piece = next(p for p in PIECES if (p["equipped_by"], p["slot"], p["level"]) == key)
    chars = _char_ids(snap)
    sp = to_scoring_profile(select_profile(profiles, chars[who]))  # type: ignore[arg-type]
    ids, _ = _rolls(snap, piece)
    art = ArtifactInput(
        slot=slot,
        rarity=5,
        level=level,
        set_name=None,
        main_stat=piece["main_stat"],
        roll_affix_ids=ids,
    )  # type: ignore[arg-type]
    got = score_artifact(art, sp, snap)
    assert (got.total_rolls, got.useful_rolls) == expected


def test_crit_value_of_a_piece_with_both_crit_substats(
    snap: Snapshot, profiles: list[CharacterProfile]
) -> None:
    piece = next(p for p in PIECES if (p["equipped_by"], p["slot"]) == ("Xinyan", "flower"))
    chars = _char_ids(snap)
    sp = to_scoring_profile(select_profile(profiles, chars["Xinyan"]))  # type: ignore[arg-type]
    ids, _ = _rolls(snap, piece)
    art = ArtifactInput(
        slot="flower",
        rarity=5,
        level=0,
        set_name=None,
        main_stat=piece["main_stat"],
        roll_affix_ids=ids,
    )
    # displayed: CRIT Rate 3.9% and CRIT DMG 7.8% -> 2 x 3.9 + 7.8 = 15.6 (exact tiers differ by < 0.1)
    assert score_artifact(art, sp, snap).crit_value == pytest.approx(15.6, abs=0.1)
