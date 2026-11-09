# Potential model v1: what an artifact piece can still become

Status: **approved in principle by Ben on 2026-11-09** (no expected value; percent of maximum both at the
maximum level and at the current level; max levels to be researched and confirmed). **Implemented 2026-11-09** (`scoring/potential.py`, `builds/rules.py`, `rules/artifact-levels.toml`, shown by
`score` and `recommend`, level-up advice in `recommend`). It extends `docs/scoring-spec.md`:
that spec rates a piece as it is today; this one says how far it can still go and how it compares with
the best possible piece.

## What it answers, in plain language

For one piece and one character profile:

1. **How much can upgrading still add?** Not a forecast: a *floor* and a *ceiling* for the roll
   score once the piece is fully upgraded.
2. **How good is it compared with the best piece that could exist?** The score as a percentage of
   the **theoretical maximum** for that slot, main stat and rarity.
3. **Which pieces are worth leveling?** Used by `recommend` to say "level this one" versus
   "replace that one".

## What it deliberately does NOT do

- **No "expected" or "typical" result.** That needs the game's odds (which substat an upgrade hits,
  which tier it rolls). Those odds are not in our data and I will not state them from memory. The
  ceiling is a best case ("every remaining upgrade hits the best stat at its top tier"), not a
  prediction, and is always labelled so. If you later want an expected value, it needs a sourced
  probability model and your approval.
- No resin or material costs, no chance of drops.

## The facts it uses, and where each comes from

| Fact | Source | Status |
|---|---|---|
| Value of every roll tier, per stat and rarity | data snapshot | cross-checked (curated) |
| A piece gains one roll every 4 levels (rolls = initial substats + level // 4) | the import already checks this on every real piece, including low-rarity ones | verified on your roster |
| A piece shows at most 4 substats; a locked fourth one is activated by the first upgrade | your `Current 5 Star Artifacts.xlsx` ("Unactivated" entries) | seen in your data |
| A piece starts with at most (rarity - 1) substats, and each upgrade activates a new substat until it shows four, then upgrades an existing one | every piece in your roster and the golden set (e.g. 4-star +10 pieces with 2 initial + 2 upgrades show 4 substats and 4 rolls) | consistent with all real pieces |
| The maximum level of each rarity | **not in our data**: the main-stat table lists levels 0-20 for every rarity. Genshin Optimizer's code (MIT, read directly, commit 283952a0): 1 star 4, 2 stars 4, 3 stars 12, 4 stars 16, 5 stars 20. A 2024 guide agrees except it gives 8 for 2 stars | `rules/artifact-levels.toml`, **provisional**: the 2-star value is open until confirmed in the game |
| Which stats can appear as substats | snapshot (10 stats) minus the piece's own main stat | data |

## Definitions

Let a roll's *value* be its tier value divided by the best 5-star tier of that stat (as in the scoring
spec), and `w(stat)` the profile weight. For a piece:

- **Upgrades left** = (max level of its rarity // 4) - (current level // 4).
- **Current score** = the roll score from the scoring spec.
- **Floor** = current score. An upgrade can only add rolls, never remove them.
- **Ceiling** = current score + the best case for the remaining upgrades:
  - if the piece already shows 4 substats: every remaining upgrade is the best `w(stat) x
    top-tier-value(stat)` among its present stats;
  - if it shows only 3 (an unlevelled piece with a locked fourth stat that our import does not
    list): the first upgrade activates a fourth stat, so the best case assumes it is the best eligible
    stat it does not already have (not the main stat), then the rest go to the best of the four. This
    is always flagged "assumes the locked substat is the best possible one".
- **Theoretical maximum** for (rarity, slot, main stat): four initial substats chosen as the highest
  weighted eligible stats at their top tier (one roll each), plus all upgrades on the single best one.
  For a 5-star piece that is 4 + 5 = 9 rolls. The main stat is excluded from eligibility, so a piece
  whose main stat is itself a favoured stat has a lower maximum.
- **Percent of maximum (at the maximum level)** = score / theoretical maximum, reported for the current
  score and for the ceiling.
- **Theoretical maximum at the current level**: the best possible piece that has had the same number of
  upgrades so far: four initial substats chosen as above (one roll each) plus (level // 4) upgrades, all on
  the single best stat. **Percent of maximum at the current level** = current score / that maximum. A piece
  that started with only three substats can never fully reach it (it has one roll fewer), and the report
  says "compared with a piece that started with four substats".

Worked example (from a throwaway prototype on your real pieces, not yet a test): Diluc's +4 5-star sands
(main stat DEF%, so all four favoured stats are eligible) scores 2.60 now, 4 upgrades left, ceiling
2.60 + 4 x 1.0 = 6.60 (its best present stat is CRIT DMG at weight 1.0), theoretical maximum
4 x 1.0 + 5 x 1.0 = 9.00, so 29% now and at best 73% of the +20 maximum; at its current level (+4) the
maximum is 4 x 1.0 + 1 x 1.0 = 5.00, so it is at 52% of what a +4 piece could be. Vesna's +20 sands (main stat Elemental Mastery,
no favoured substat) scores 0.00 with nothing left to upgrade, against a maximum of 8.00: 0%.

## Where it appears

- `scoring/potential.py` (pure, like the rest of `scoring`): `potential(art, profile, snapshot,
  rules)`; the result is a new `potential` field on `ArtifactScore` (levels left, floor, ceiling,
  theoretical maximum, both percentages, assumptions, problems).
- `score` and `recommend` show it per piece ("+4, 4 upgrades left: 2.60 now, 6.60 at best, 29% / 73% of
  the maximum").
- `recommend` gains **level-up advice**: pieces below max level whose main stat and set are fine, best
  current rolls first (invest where the rolls are already good), alongside the existing "replace" advice.
- Anything not modelled (a rarity whose max level is unknown) says so and shows no potential, never a
  guess.

## Tests

- Formula tests on the small hand-made tier table, expected values worked out in the test:
  floor/ceiling for 4-substat and 3-substat pieces, main-stat exclusion, 4-star scale, a maxed piece
  (ceiling equals current), a profile with no favoured stats (maximum 0, percentages undefined and shown
  as such, never divided by zero).
- Property tests: ceiling >= floor >= 0; the percentage of maximum is between 0 and 100; adding an
  upgrade never lowers the ceiling; raising a weight never lowers the maximum; roll order never matters.
- Golden tests on your 11 pieces (real snapshot): every piece obeys the invariants above, your +20 piece
  has ceiling equal to its current score, and the theoretical maximum equals the arithmetic done by hand
  from the tier table (an independent route).

## Decisions

(Implementation note: a piece that shows fewer than four substats must spend its next upgrades activating
new ones, so the best case adds the best unused eligible stats first; a +8 piece with a single substat would
therefore get no extra ceiling. Real pieces never look like that.)

1. **No expected value in v1** (range and best case only): approved by Ben.
2. **Max levels per rarity**: Ben is not sure either except +20 for 5-star, so they are being researched from
   independent public sources (Genshin Optimizer's code, a wiki, a guide site) and compared mechanically.
   They will be stored in a small curated data file with the sources and dates as provenance, marked
   provisional until Ben confirms them in the game. Until a rarity's maximum is established, it shows no
   potential and says why.
3. **Both percentages are shown**: of the +max maximum, and of the maximum at the current level
   (approved by Ben).
