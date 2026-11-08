"""Human-readable difference between two snapshots (new characters, changed weapons, ...)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from genshin_companion.data.models import Snapshot

_DATASETS = ("characters", "weapons", "artifact_sets", "artifacts")


@dataclass(slots=True)
class EntityDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.changed)


@dataclass(slots=True)
class Changelog:
    old_version: str
    new_version: str
    entities: dict[str, EntityDiff]
    tier_changes: list[str]
    main_stat_changes: list[str]
    confidence_changes: list[str]

    @property
    def has_changes(self) -> bool:
        return bool(
            self.old_version != self.new_version
            or any(e.any for e in self.entities.values())
            or self.tier_changes
            or self.main_stat_changes
            or self.confidence_changes
        )


def _label(item: BaseModel) -> str:
    name = getattr(item, "name", None)
    return f"{name} ({item.id})" if name else str(item.id)  # type: ignore[attr-defined]


def _diff_entities(old: list[BaseModel], new: list[BaseModel]) -> EntityDiff:
    before = {o.id: o for o in old}  # type: ignore[attr-defined]
    after = {n.id: n for n in new}  # type: ignore[attr-defined]
    out = EntityDiff()
    out.added = [_label(after[k]) for k in sorted(after.keys() - before.keys())]
    out.removed = [_label(before[k]) for k in sorted(before.keys() - after.keys())]
    out.changed = [
        _label(after[k]) for k in sorted(after.keys() & before.keys()) if after[k] != before[k]
    ]
    return out


def diff(old: Snapshot, new: Snapshot) -> Changelog:
    entities = {
        name: _diff_entities(list(getattr(old, name)), list(getattr(new, name)))
        for name in _DATASETS
    }
    old_t = {(t.rarity, t.stat, t.position): t.value for t in old.substat_tiers}
    new_t = {(t.rarity, t.stat, t.position): t.value for t in new.substat_tiers}
    tier_changes = [
        f"rarity {k[0]} {k[1]} tier {k[2]}: {old_t[k]} -> {new_t[k]}"
        for k in sorted(old_t.keys() & new_t.keys())
        if old_t[k] != new_t[k]
    ]
    old_m = {(m.rarity, m.level, m.stat): m.value for m in old.main_stats}
    new_m = {(m.rarity, m.level, m.stat): m.value for m in new.main_stats}
    main_changes = [
        f"rarity {k[0]} level {k[1]} {k[2]}: {old_m[k]} -> {new_m[k]}"
        for k in sorted(old_m.keys() & new_m.keys())
        if old_m[k] != new_m[k]
    ]
    conf = [
        f"{k}: {old.confidence.get(k, 'n/a')} -> {new.confidence.get(k, 'n/a')}"
        for k in sorted(old.confidence.keys() | new.confidence.keys())
        if old.confidence.get(k) != new.confidence.get(k)
    ]
    return Changelog(old.game_version, new.game_version, entities, tier_changes, main_changes, conf)


def render(cl: Changelog) -> str:
    lines = [f"# Data changelog: game version {cl.old_version} -> {cl.new_version}", ""]
    if not cl.has_changes:
        return "\n".join([*lines, "No changes.", ""])
    for name, section in cl.entities.items():
        if not section.any:
            continue
        lines.append(f"## {name.replace('_', ' ').title()}")
        for title, items in (
            ("Added", section.added),
            ("Removed", section.removed),
            ("Changed", section.changed),
        ):
            if items:
                shown = items[:50]
                lines.append(
                    f"- **{title} ({len(items)}):** "
                    + ", ".join(shown)
                    + (" ..." if len(items) > 50 else "")
                )
        lines.append("")
    for title, items in (
        ("Substat roll values changed", cl.tier_changes),
        ("Main stat values changed", cl.main_stat_changes),
        ("Confidence changed", cl.confidence_changes),
    ):
        if items:
            lines.append(f"## {title} ({len(items)})")
            lines.extend(f"- {i}" for i in items[:50])
            lines.append("")
    return "\n".join(lines)
