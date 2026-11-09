"""Rate an imported roster: translate roster pieces into scoring inputs, score them, print them.

All numbers come from ``genshin_companion.scoring`` (pure) and the data snapshot; this module only
maps types and formats text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from pydantic import ValidationError

from genshin_companion.app.report import stat_label
from genshin_companion.builds.profiles import CharacterProfile
from genshin_companion.builds.scoring_profile import select_profile, to_scoring_profile
from genshin_companion.data.models import Snapshot
from genshin_companion.enka.models import ImportedArtifact, Roster
from genshin_companion.scoring import (
    ArtifactInput,
    ArtifactRules,
    ArtifactScore,
    ScoringProfile,
    score_artifact,
)
from genshin_companion.scoring.character import SLOT_ORDER, CharacterSummary, summarize_character
from genshin_companion.scoring.models import Slot

SLOT_BY_EQUIP: Final[dict[str, Slot]] = {
    "EQUIP_BRACER": "flower",
    "EQUIP_NECKLACE": "plume",
    "EQUIP_SHOES": "sands",
    "EQUIP_RING": "goblet",
    "EQUIP_DRESS": "circlet",
}


@dataclass(frozen=True, slots=True)
class PieceResult:
    slot: Slot
    level: int
    rarity: int
    main_stat: str
    set_name: str | None
    score: ArtifactScore


@dataclass(frozen=True, slots=True)
class CharacterResult:
    avatar_id: int
    name: str
    level: int
    profile: ScoringProfile | None
    pieces: tuple[PieceResult, ...] = ()
    summary: CharacterSummary | None = None
    notes: tuple[str, ...] = field(default=())
    chosen: CharacterProfile | None = None  # the profile the scores came from


def _safe(text: str, limit: int = 120) -> str:
    """Text from a roster or snapshot is untrusted: no control characters reach the terminal."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)[:limit]


def _artifact_input(
    art: ImportedArtifact, slot: Slot, set_names: dict[str, str | None]
) -> ArtifactInput:
    return ArtifactInput(
        slot=slot,
        rarity=art.rarity,
        level=art.level,
        set_name=_set_name(set_names, art),
        main_stat=art.main_stat,
        roll_affix_ids=list(art.roll_affix_ids),
    )


def _set_name(set_names: dict[str, str | None], art: ImportedArtifact) -> str | None:
    name = set_names.get(str(art.set_id)) if art.set_id is not None else None
    return _safe(name, 300) or None if name else None


def score_roster(
    roster: Roster,
    snapshot: Snapshot,
    profiles: list[CharacterProfile],
    rules: ArtifactRules | None = None,
) -> list[CharacterResult]:
    names = {c.id: c.name for c in snapshot.characters}
    set_names: dict[str, str | None] = {s.id: s.name for s in snapshot.artifact_sets}
    results: list[CharacterResult] = []
    for ch in roster.characters:
        name = _safe(names.get(str(ch.avatar_id)) or f"avatar {ch.avatar_id}")
        chosen = select_profile(profiles, str(ch.avatar_id))
        if chosen is None:
            results.append(CharacterResult(ch.avatar_id, name, ch.level, None))
            continue
        profile = to_scoring_profile(chosen)
        pieces: dict[Slot, PieceResult] = {}
        notes: list[str] = []
        if chosen.character_id != str(ch.avatar_id):
            notes.append(
                f"profile {chosen.character_id} was matched by base id {ch.avatar_id}; the roster "
                "does not record the variant (element), so check it is the right one"
            )
        for art in ch.artifacts:
            slot = SLOT_BY_EQUIP.get(art.slot)
            if slot is None:
                notes.append(f"piece in unknown slot {_safe(art.slot)} was not scored")
            elif slot in pieces:
                notes.append(f"a second piece in slot {slot} was not scored")
            else:
                try:
                    piece_input = _artifact_input(art, slot, set_names)
                except ValidationError:
                    notes.append(f"the {slot} piece has out-of-range data: not scored")
                    continue
                score = score_artifact(piece_input, profile, snapshot, rules)
                pieces[slot] = PieceResult(
                    slot, art.level, art.rarity, art.main_stat, piece_input.set_name, score
                )
        summary = summarize_character({s: p.score for s, p in pieces.items()})
        results.append(
            CharacterResult(
                ch.avatar_id,
                name,
                ch.level,
                profile,
                tuple(pieces[s] for s in SLOT_ORDER if s in pieces),
                summary,
                tuple(notes),
                chosen,
            )
        )
    return results


def _fit_text(score: ArtifactScore) -> tuple[str, str]:
    m = score.main_stat_fit
    if m.status == "fixed":
        main = "(fixed slot)"
    elif m.status == "recommended":
        pct = f" ({m.usage_percent:g}% of players)" if m.usage_percent is not None else ""
        main = f"is recommended{pct}"
    elif m.status == "conditional":
        main = f"is conditional: {_safe(m.condition or '')}"
    elif m.status == "not_listed":
        main = "is NOT on the recommended list"
    else:
        main = "no recommendation recorded"
    s = score.set_fit
    if s.status == "other":
        set_text = "(not a recommended set)"
    else:
        pct = f", {s.usage_percent:g}% of players" if s.usage_percent is not None else ""
        set_text = f"({s.status}{pct})"
    return main, set_text


def _pct(x: float | None) -> str:
    return f"{x:.0%}" if x is not None else "n/a"


def _potential_line(level: int, score: ArtifactScore) -> str | None:
    p = score.potential
    if p.status != "modelled":
        return None
    prefix = "           potential: "
    if (p.upgrades_left or 0) == 0:
        return f"{prefix}fully upgraded: {_pct(p.pct_of_max)} of the +{p.max_level} maximum"
    left = p.upgrades_left
    return (
        f"{prefix}{left} upgrade{'s' if left != 1 else ''} left: {score.roll_score:.2f} now, "
        f"up to {p.ceiling or 0.0:.2f} at best; "
        f"{_pct(p.pct_of_max_now_level)} of a +{level} maximum, "
        f"{_pct(p.pct_of_max)} of the +{p.max_level} maximum (at best {_pct(p.pct_ceiling_of_max)})"
    )


def render_scores(results: list[CharacterResult]) -> str:
    out: list[str] = []
    for r in results:
        out.append(f"\n{r.name}  Lv{r.level}")
        if r.profile is None:
            out.append("  no profile recorded for this character: not scored")
            continue
        pr = r.profile
        out.append(
            f"  [{pr.confidence}, {pr.kind} profile read {pr.observed_at}; "
            "scores are provisional until a profile is approved]"
            if pr.confidence == "provisional"
            else f"  [{pr.confidence}, {pr.kind} profile read {pr.observed_at}]"
        )
        for piece in r.pieces:
            sc = piece.score
            main_text, set_text = _fit_text(sc)
            out.append(
                f"  {piece.slot:8} +{piece.level:<2} {piece.rarity}*"
                f"  roll score {sc.roll_score:.2f}"
                f"  ({sc.total_rolls} roll{'s' if sc.total_rolls != 1 else ''},"
                f" {sc.useful_rolls} on favoured stats,"
                f" {sc.average_per_roll:.2f} per roll)  crit value {sc.crit_value:.1f}"
            )
            out.append(
                f"           main stat: {stat_label(piece.main_stat)} {main_text}"
                f"   set: {_safe(piece.set_name or 'unknown')} {set_text}"
            )
            out.extend(
                f"           not scored: {stat_label(n.stat)} ({n.condition}) on {n.rolls} roll"
                + ("s" if n.rolls != 1 else "")
                for n in sc.not_scored
            )
            out.extend(f"           ! {_safe(p)}" for p in sc.problems)
            potential = _potential_line(piece.level, sc)
            if potential:
                out.append(potential)
        reasons = sorted({p.score.potential.reason for p in r.pieces if p.score.potential.reason})
        if reasons:
            out.append("  potential not shown: " + "; ".join(_safe(x, 200) for x in reasons))
        if r.summary is not None:
            s = r.summary
            parts = [f"total roll score {s.total_roll_score:.2f} over {s.pieces_scored} piece(s)"]
            if s.weakest_slot:
                parts.append(f"weakest: {s.weakest_slot}")
            if s.missing_slots:
                parts.append(f"missing: {', '.join(s.missing_slots)}")
            if s.main_stat_not_listed:
                parts.append(f"main stat not on the list: {', '.join(s.main_stat_not_listed)}")
            out.append("  summary: " + "; ".join(parts))
        if pr.weights_note:
            out.append(f"  note: {pr.weights_note}")
        out.extend(f"  note: {_safe(n, 300)}" for n in r.notes)
    return "\n".join(out).lstrip("\n")
