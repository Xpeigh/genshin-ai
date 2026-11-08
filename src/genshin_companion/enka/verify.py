"""Self-check of an imported artifact against the synced snapshot.

Enka lists the affix id of every roll. The snapshot knows each id's stat, rarity and tier value, so
the displayed substat value must equal the sum of its rolls. A mismatch means the import or the
snapshot is wrong; it is reported, never silently "fixed".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from genshin_companion.data.models import Snapshot, SubstatTier
from genshin_companion.enka.models import ImportedArtifact

# Substats displayed as plain numbers; every other stat is displayed in percent (value * 100).
FLAT_STATS = frozenset(
    {"FIGHT_PROP_HP", "FIGHT_PROP_ATTACK", "FIGHT_PROP_DEFENSE", "FIGHT_PROP_ELEMENT_MASTERY"}
)
MAX_INITIAL_SUBSTATS = 4


@dataclass(slots=True)
class ArtifactCheck:
    rolls: dict[str, list[int]] = field(default_factory=dict)  # stat -> tier positions in order
    initial_substats: int = 0
    upgrades: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def tier_index(snapshot: Snapshot) -> dict[str, SubstatTier]:
    return {t.affix_id: t for t in snapshot.substat_tiers}


def check_artifact(
    art: ImportedArtifact, snapshot: Snapshot, index: dict[str, SubstatTier] | None = None
) -> ArtifactCheck:
    index = index if index is not None else tier_index(snapshot)
    out = ArtifactCheck()
    sums: dict[str, float] = defaultdict(float)
    rolls: dict[str, list[int]] = defaultdict(list)
    for affix_id in art.roll_affix_ids:
        tier = index.get(affix_id)
        if tier is None:
            out.problems.append(f"roll id {affix_id} is not in the data snapshot")
            continue
        if tier.rarity != art.rarity:
            out.problems.append(
                f"roll id {affix_id} is a rarity-{tier.rarity} roll on a rarity-{art.rarity} piece"
            )
        rolls[tier.stat].append(tier.position)
        sums[tier.stat] += tier.value
    out.rolls = dict(rolls)

    out.upgrades = art.level // 4
    out.initial_substats = len(art.roll_affix_ids) - out.upgrades
    # Low-rarity pieces can have no substats at all, so zero initial substats is legitimate.
    if not 0 <= out.initial_substats <= MAX_INITIAL_SUBSTATS:
        out.problems.append(
            f"{len(art.roll_affix_ids)} rolls at level {art.level} implies "
            f"{out.initial_substats} initial substats"
        )

    shown = {s.stat: s.value for s in art.substats}
    for stat in sorted(set(shown) ^ set(rolls)):
        out.problems.append(f"{stat}: listed substats and roll ids disagree")
    for stat, value in shown.items():
        if stat not in sums:
            continue
        expected = sums[stat] if stat in FLAT_STATS else sums[stat] * 100
        tolerance = 0.51 if stat in FLAT_STATS else 0.051
        if abs(expected - value) > tolerance:
            out.problems.append(
                f"{stat}: rolls add up to {expected:.3f} but the game shows {value}"
            )
    return out
