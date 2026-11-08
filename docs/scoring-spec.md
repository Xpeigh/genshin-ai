# Scoring engine v1: piece scoring

Status: **approved by Ben on 2026-11-08 and implemented** (piece scoring, per-character summary and
the `genshin-companion score` command). Changes made while building are listed under
"Differences from the first draft" at the end.

Scope of v1: score ONE artifact piece against ONE character profile. Not in v1 (listed at the end):
"% of theoretical maximum", potential for unleveled pieces, per-character totals, weapon scoring.

## What a score means (plain language)

A piece gets three separate facts. They are **not** merged into one grade, because mixing them
would hide why a piece is good or bad.

1. **Main stat fit**: is this piece's main stat on the character's recommended list for that slot,
   and what share of players use it (the in-game percentage)? Flower and plume are fixed.
2. **Set fit**: is the piece's set one of the recommended sets (best or alternative), with its share.
3. **Roll score**: how good were the substat rolls for this character?

## The roll score (approved rule)

- Every substat roll on the piece is known exactly (Enka lists one id per roll; the data snapshot
  says which stat and which tier value each id is).
- A roll's **value** = its tier value divided by the best 5-star tier value of that stat. A perfect
  5-star roll is 1.0; a 4-star roll is worth less. Both numbers come from the snapshot.
- A roll's **weight** comes from the character's profile: 1.0 for a favoured stat, 0 for any other.
- **Roll score** = sum over all rolls of weight x value. Also reported: rolls on favoured stats
  ("useful rolls") out of all rolls, and the average score per roll.
- **Crit value** (baseline summary metric from SPEC.md) = 2 x CRIT Rate + CRIT DMG, from the actual
  substat totals in percent. Reported for every piece, whether or not the profile favours crit.
- Rolls on the piece's own main stat cannot exist in the game. If the data says otherwise it is
  reported as a problem and never silently scored.

Illustrative result from a throwaway prototype on a real piece: Diluc's +4 5-star sands has 4 rolls,
3 on favoured stats, roll score 2.60; Vesna's +20 5-star Elemental Mastery sands has 8 rolls, none
favoured, roll score 0.00. These become tests only after Ben has checked them by hand.

## Turning a profile into weights

- **in-game profile**: the favoured substats are an unordered set (Ben confirmed the order carries no
  meaning) -> every favoured stat has weight 1.0, whatever tiers the file happens to have.
- **guide profile**: ranked tiers -> tier 1 = 1.0, tier 2 = 0.75, tier 3 = 0.5, tier 4 = 0.25 (a
  convention, one constant `GUIDE_TIER_STEP = 0.25`, floor 0.25; it is invented, not game data, and
  is labelled as such in every guide-based result).
- **conditional stats** ("only with Favonius Lance", "only up to the ER target"): weight 0, and the
  result lists them as "not scored: <condition>" with the number of rolls affected, so nothing is
  hidden. Whether to score them is a later decision.
- **Which profile**: an exact id match wins; if there is none, a profile keyed per variant
  (`10000007-705`) answers for its base avatar only when exactly one variant exists (several variants
  cannot be told apart because the roster does not record the element, so nothing is scored). Among
  equally exact matches the in-game profile beats the guide one. A variant match is flagged in the
  report.
- Every guide-based result carries the note that its weights are a convention.

## Module layout (respects the enforced dependency direction)

`scoring` may import only `scoring` and `data` (enforced by `tests/test_architecture.py`), so it
cannot read profiles (`builds`) or imported artifacts (`enka`). It defines its own small inputs and
the other layers translate:

- `scoring/models.py`: `ArtifactInput` (slot, rarity, level, set name, main stat, roll ids),
  `ScoringProfile` (stat weights, unscored conditional stats with their conditions, recommended main
  stats per slot with usage %, recommended sets with usage %, provenance), `ArtifactScore`
  (everything below), all frozen pydantic models.
- `scoring/artifact.py`: `score_artifact(artifact, profile, snapshot) -> ArtifactScore`. Pure: no
  I/O, no clock, no randomness, no network. Same input + same snapshot = identical output.
- `scoring/character.py`: `summarize_character(scores)`: total roll score, weakest and strongest slot,
  missing slots, main stats not on the list, pieces in a recommended set.
- `builds/scoring_profile.py`: `to_scoring_profile(profile)` applies the weights rule above;
  `select_profile(profiles, character_id)` picks the in-game profile over the guide one.
- `app/score.py` and the `score` CLI command: map `ImportedArtifact` to `ArtifactInput`, score every
  piece of every imported character, print the breakdown.

## Output (the breakdown a test or the chat layer can quote)

`ArtifactScore`: roll score; total rolls; useful rolls; average per roll; one line per stat (rolls,
tier values, contribution), sorted by stat id so output is deterministic; the not-scored conditional
rolls; crit value; main stat fit (`fixed` | `recommended` | `conditional` | `not_listed`, usage %,
condition); set fit (`best` | `alternative` | `other`, usage %); problems; and provenance:
`profile_kind`, `profile_source`, `profile_observed_at`, `data_version` (snapshot game version) and
`confidence` = the weakest of the profile's, the roll data's and (when the piece has a set) the set
data's (so provisional until Ben approves the profile and the data is cross-checked).

## Tests

- **Formula tests** on the synthetic snapshot fixture, with expected numbers worked out by hand in
  the test itself (e.g. tier 700 / best 900 = 0.78 per roll). These check the arithmetic, not game
  numbers.
- **Profile-to-weights tests**: in-game, guide tiers, conditional stats, both-kinds preference.
- **Property tests**: swapping the order of rolls or of favoured stats never changes the score;
  weights of 0 everywhere give 0; every score is >= 0 and <= total rolls.
- **Architecture tests** already forbid network, LLM or file access inside `scoring`.
- **Golden tests** (`tests/test_scoring_golden.py`, fixture `tests/fixtures/golden_artifacts.json`) use
  the 11 real pieces Ben copied from the game. They need the real snapshot (never committed), via
  `GENSHIN_REAL_SNAPSHOT`; `tasks.py check` sets it automatically when `data-home` has one. Nothing is
  invented: the roll score is linear in the displayed totals, so each piece must score exactly
  weight x (displayed total / best five-star roll) summed over its favoured stats, an independent
  route to the engine's per-roll arithmetic. Roll and useful-roll counts are plain counts of the
  substats Ben typed in. Every displayed substat must also split into whole rolls in exactly one way,
  and every main-stat value must match the snapshot at that level.

## Not in v1 (next steps, in order)

1. "% of theoretical maximum" and the potential range for unleveled pieces (needs a documented
   upgrade model; never a single point estimate).
2. Per-character summary: total roll score, weakest slot, missing slots.
3. `genshin-companion score` command and the report.
4. Weapon scoring (base stats from the snapshot, recommended weapons from profiles).
5. Whether and how to score conditional stats (needs team and weapon context).

## Differences from the first draft

- **Unactivated substats** (a +0 piece shows a fourth substat that is still locked) are not rolls yet:
  they are not scored and not counted. The Enka import does not list them either.
- `to_scoring_profile` does not need the snapshot, so it takes only the profile.
- Steps 2 and 3 of "next steps" (per-character summary, `score` command) were built together with v1.
- **Known limit:** a Traveler profile is keyed per element (`10000007-705` is Cryo) but the roster
  import records only the base avatar id, so the profile is matched without checking the element.

## Independent review (2026-11-08)

Three reviewers (spec conformance, purity and untrusted input, test quality) found 28 issues; the
confirmed ones are fixed, each with a test that failed first:

- a Traveler of another element would have been scored with the Cryo profile (exact ids now win,
  ambiguous variants match nothing, a single variant match is flagged);
- in-game profiles with several tiers did not get weight 1.0, and guide results were not always
  labelled;
- confidence ignored the set data;
- set fit let a conditional listing hide an unconditional one;
- weights outside 0..1, NaN, or a stat both weighted and "not scored" were accepted;
- odd roster data (bad main stat, too many rolls, control characters, an unreadable saved roster or
  profile file, a 5000-digit integer) crashed the `score` command instead of giving a note or a clean
  error, and untrusted text could reach the terminal;
- sums depended on roll order in the last bit (now `math.fsum`), and a one-bit difference could
  break a "tie" between pieces;
- the architecture test did not forbid scoring from reaching file I/O through `data` (it does now);
- many untested branches and report details, and a golden test that could skip silently, are now
  covered.

