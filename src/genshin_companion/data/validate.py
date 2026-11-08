"""Sanity and diff-size checks on a candidate snapshot before it can be promoted.

``rejected``: structurally wrong, never promote. ``held``: plausible but suspicious (large or odd
change versus the last-known-good snapshot); needs an explicit human override. ``ok``: promote.
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Final, Literal

from genshin_companion.data.changelog import diff
from genshin_companion.data.models import Snapshot

MAX_CHANGED_FRACTION: Final = 0.20
REQUIRED_DATASETS: Final = (
    "substat_tiers", "main_stats", "characters", "weapons", "artifact_sets",
)  # fmt: skip
_RANK = {"verified": 3, "curated": 2, "provisional": 1}


@dataclass(slots=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)

    @property
    def status(self) -> Literal["ok", "held", "rejected"]:
        if self.errors:
            return "rejected"
        return "held" if self.review_reasons else "ok"


def _version(v: str) -> tuple[int, int] | None:
    try:
        major, minor = v.split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def _structural(snap: Snapshot, report: ValidationReport) -> None:
    for name in REQUIRED_DATASETS:
        if not getattr(snap, name):
            report.errors.append(f"dataset {name} is empty")
    for label, ids in (
        ("characters", [c.id for c in snap.characters]),
        ("weapons", [w.id for w in snap.weapons]),
        ("artifact_sets", [s.id for s in snap.artifact_sets]),
        ("artifacts", [a.id for a in snap.artifacts]),
        ("substat_tiers", [f"{t.rarity}/{t.stat}/{t.position}" for t in snap.substat_tiers]),
        ("main_stats", [f"{m.rarity}/{m.level}/{m.stat}" for m in snap.main_stats]),
    ):
        if len(ids) != len(set(ids)):
            report.errors.append(f"duplicate entries in {label}")
    if not all(math.isfinite(t.value) for t in snap.substat_tiers) or not all(
        math.isfinite(m.value) for m in snap.main_stats
    ):
        report.errors.append("non-finite stat value")

    per_rarity: dict[int, set[int]] = defaultdict(set)
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for t in snap.substat_tiers:
        counts[(t.rarity, t.stat)] += 1
    for (rarity, _), n in counts.items():
        per_rarity[rarity].add(n)
    for rarity, sizes in per_rarity.items():
        if len(sizes) > 1:
            report.errors.append(
                f"inconsistent substat tier counts at rarity {rarity}: {sorted(sizes)}"
            )

    series: dict[tuple[int, str], list[tuple[int, float]]] = defaultdict(list)
    for m in snap.main_stats:
        series[(m.rarity, m.stat)].append((m.level, m.value))
    for (rarity, stat), points in series.items():
        values = [v for _, v in sorted(points)]
        if any(b < a for a, b in itertools.pairwise(values)):
            report.errors.append(f"main stat {stat} at rarity {rarity} would decrease with level")


def _against_previous(new: Snapshot, old: Snapshot, report: ValidationReport) -> None:
    nv, ov = _version(new.game_version), _version(old.game_version)
    if ov is not None and nv is None:
        report.review_reasons.append(f"game version became unknown (was {old.game_version})")
    elif nv is not None and ov is not None and nv < ov:
        report.review_reasons.append(
            f"game version went backwards: {old.game_version} -> {new.game_version}"
        )

    cl = diff(old, new)
    if cl.tier_changes:
        report.review_reasons.append(
            f"substat roll values changed for {len(cl.tier_changes)} existing tier(s); "
            "these should never change within a patch"
        )
    if cl.main_stat_changes:
        report.review_reasons.append(
            f"main stat curve changed in {len(cl.main_stat_changes)} place(s)"
        )
    for dataset, count_before in (
        ("characters", len(old.characters)),
        ("weapons", len(old.weapons)),
        ("artifact_sets", len(old.artifact_sets)),
    ):
        section = cl.entities[dataset]
        if count_before and len(section.removed) / count_before > MAX_CHANGED_FRACTION:
            report.review_reasons.append(
                f"{len(section.removed)} of {count_before} {dataset} disappeared"
            )
        elif section.removed:
            report.warnings.append(f"{len(section.removed)} {dataset} removed")
        if count_before and len(section.changed) / count_before > MAX_CHANGED_FRACTION:
            report.review_reasons.append(
                f"{len(section.changed)} of {count_before} {dataset} changed"
            )
    for dataset, then in old.confidence.items():
        now = new.confidence.get(dataset)
        if now is not None and _RANK[now] < _RANK[then]:
            report.warnings.append(f"confidence for {dataset} dropped from {then} to {now}")


def validate(new: Snapshot, previous: Snapshot | None) -> ValidationReport:
    report = ValidationReport()
    _structural(new, report)
    if previous is not None and not report.errors:
        _against_previous(new, previous, report)
    return report
