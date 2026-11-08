# Plan: Genshin Companion (working title)

Local-first Genshin Impact assistant: UID import, artifact/weapon scoring, build recommendations, lore Q&A, and (later) team rankings. Packaged as a small desktop/local app that runs on modest hardware.

Status legend: [ ] todo, [x] done. Update as you go and add newly discovered tasks immediately.

## Phase 0: Scaffolding
- [x] Repo layout (see SPEC.md, "Module boundaries"), Python project, lint/format/test tooling (uv, ruff, mypy strict, pytest; added `net/` package)
- [x] CLAUDE.md with conventions (copy the "Hard rules" from SPEC.md)
- [x] CI-style local script: `python -m uv run python tasks.py check` runs lint + format + mypy + tests + dependency audit (no `make` on Windows; decided with Ben)

## Phase 0b: Security foundations (do before any network code)
- [x] Single HTTP client module (adversarial review pending): GET/HEAD only, HTTPS only, domain allowlist in config, timeouts, size caps, allowlist-bound redirects
- [x] Test or lint rule that fails if any other module imports an HTTP library (`tests/test_architecture.py` + ruff TID251; also covers scoring purity, chat reach, dependency direction)
- [x] Dependency lock file with hashes (`uv.lock`) and pip-audit step in `tasks.py check`
- [x] Local data directory layout (`paths.py`) and `genshin-companion clear-data --yes` (marker-file guarded, symlink-safe)
- [x] README section: exactly what the app does and does not send over the network (UID goes to Enka in the lookup URL)

## Phase 1: Data layer and sync
- [x] Choose and document data sources (genshin-db, Ambr/Project Amber, Enka store files). Verify licenses and terms first. Research in `docs/data-sources.md`; Ben chose Enka primary (pinned SHA) + Project Amber cross-check; genshin-db deferred
- [x] Normalized local data snapshot (JSON, pydantic) with `game_version` (from Amber changelog, else `unknown`), `fetched_at`, per-file sha256 and pin status; integrity hash, quarantine, last-known-good history (5), `snapshot rollback`
- [x] `sync` command (manual): validate, diff-size gate (`held` needs `--accept-held`), CHANGELOG.md per snapshot. Scheduled sync not done yet
- [x] Characters, weapons, artifact sets, main-stat curves, substat roll tiers all come from data (real sync verified: 156 characters, 256 weapons, 65 sets, 170 tiers; tiers and main stats cross-checked `curated`)

## Phase 2: Scoring engine (the heart of the project)
- [ ] Pure, deterministic library: no network, no LLM, no file I/O inside scoring functions
- [x] Weights rule approved by Ben 2026-11-08 (favoured = 1.0, roll value = tier value / best 5-star tier, guide tiers 1.0/0.75/0.5/0.25, conditional stats weight 0 and flagged). Spec: `docs/scoring-spec.md` (awaiting Ben's review before code)
- [x] Artifact scoring v1 built per `docs/scoring-spec.md` (piece roll score, useful rolls, crit value, main stat and set fit, per-character summary, `genshin-companion score`), independently reviewed (28 findings, confirmed ones fixed with tests). Golden tests run on Ben's 11 hand-copied 5-star pieces (two sheet label typos confirmed by Ben)
- [ ] Scoring next steps: '% of theoretical maximum' and potential range for unleveled pieces (documented upgrade model), weapon scoring, whether to score conditional stats
- [ ] Capture the Traveler's element in the Enka import (skill depot) so a variant profile can be matched exactly
- [ ] Snapshot validation does not check names (empty or control characters); the score command sanitises at its boundary, but `data/validate.py` should reject bad names
- [ ] Weapon scoring and ranking per character (stat-based first, curated passive tags second)
- [ ] Golden tests with hand-verified artifacts (ask Ben to supply a few real pieces)
- [ ] Stat-weight profiles per character and role (curated data file, versioned)

## Phase 3: UID import
- [x] Enka client with descriptive User-Agent, on-disk cache that respects the response TTL, typed errors (400/404/424/429 with Retry-After/5xx; private showcase = 200 without characters)
- [x] Map Enka payload to internal models (`enka/mapping.py`); synthetic fixtures; rolls decomposed and self-checked against the snapshot (20/20 real artifacts from Enka's example account matched)
- [ ] CLI: `import <uid>` and `roster` done (`--file` for offline import); `score` waits for Phase 2. **Ben's own showcase is empty: add characters to the in-game Character Showcase and re-import**

## Phase 4: Build recommendations
- [ ] Per-character recommended sets, main stats, substat priority, weapon list, sourced from the curated profiles
- [ ] Every recommendation carries `source`, `data_version` and a `confidence` label

## Phase 4b: Local API and UI shell
- [ ] Local backend (FastAPI or similar) exposing the scoring, builds, roster and team-ranking data; the CLI and the UI both use it
- [ ] Web UI served by that backend, runnable in a normal browser first (shell-agnostic)
- [ ] Screens: roster and artifact scoring, build recommendations, team comps (reads `team_rankings.json`), chat panel (after Phase 5)
- [ ] Genshin-inspired visual style using original CSS/design, with game icons fetched at runtime from data sources; see asset note in SPEC.md
- [ ] Wrap in a desktop shell (Tauri with a Python sidecar is the leading candidate; decide with Ben after a spike)

## Phase 5: Chat layer (small local model)
- [ ] Ollama wrapper with tool calling; the model only calls tools and phrases results
- [ ] Tools: get_character, get_build, score_artifact, score_roster, get_weapon, search_lore, get_patch_changes
- [ ] Benchmark candidate small models (about 3-4B class) on tool-call reliability and refusal-to-guess behavior; document the winner and why
- [ ] Guardrail: if no tool result supports a claim, the assistant says it doesn't know

## Phase 6: Patch ingestion and confidence labels
- [ ] Fetch official patch notes, LLM-assisted parsing into structured diffs, flagged for human review
- [ ] "Provisional" label for newly released characters and anything older than the current data version

## Phase 7: Lore RAG
- [ ] Ingest dialogue, item descriptions, wiki text (check each source's terms), local embeddings, citations in answers

## Phase 8: Simulation and offline team analyzer (runs on Ben's PC)
Scope principle: never brute-force every variable (character x level x C0-C6 x talents x weapon x refinement x artifacts x enemy). That space is astronomically large and mostly redundant. Coverage grows in priority tiers, and only characters whose kit module has passed validation get published rankings. Everything else is labelled `provisional`.

- [ ] 8a Damage engine: deterministic, data-driven. Formulas live in code, every number (base stats, scaling, multipliers) comes from the snapshot. Unit tests for each formula term (base damage, crit, DMG bonus, defence, resistance, amplifying and additive reactions, etc.)
- [ ] 8b Kit modules: one per character, encoding triggers, durations, stacking and conditional buffs. Level, constellation (C0-C6) and talent level are parameters, with a unit test per constellation effect. Each module has a status: `unvalidated` or `validated`
- [ ] 8c Layered validation harness. A module is `validated` only if it passes every layer that applies:
  - Layer 1, formula layer: about 20-30 in-game readings recorded by Ben, once, to validate crit, defence, resistance, reaction and bonus terms. Fixture = character, level, C, weapon and refinement, artifacts (auto-filled from an Enka import), enemy, action, observed damage, and a stated tolerance. Ben only hits the dummy and types the number
  - Layer 2, automated cross-check: run identical configurations through an established open calculator (Genshin Optimizer is the leading candidate) and compare. Check each tool's license and terms first. Spike: can it run headless? Agreement of our engine with one or two independent references across thousands of configs is strong evidence but not ground truth
  - Layer 3, spot checks: new characters and any disagreement between our engine and the references get fresh readings from Ben
  - Report all disagreements; never hide them. Re-run the whole harness after every patch sync
- [ ] 8c-opt (optional, later experiment): passive screen-capture plus number recognition to speed up readings. Strictly passive: no input automation, no memory reading, no game modification. Read HoYoverse's current terms before building anything, and test on a throwaway setup first
- [ ] 8d Scenario runner: multiprocess, resumable with checkpoints, estimates runtime before starting, writes versioned result files
- [ ] 8e Pruned sweeps: level at meaningful breakpoints, all of C0-C6 per character, weapons filtered by weapon type then a candidate set, artifact sets from a per-character candidate list, enemies as archetypes (single target, multi target, resistance classes, shielded) instead of every enemy. Then team enumeration by role slot and rotation templates
- [ ] 8f Output: `team_rankings.json` with assumptions, validated flags and patch version; the app only reads this file
- [ ] Decide: reuse Genshin Optimizer formulas (check license) vs. own model. Check Paimon+ repo license before looking at its code

## Phase 9: Packaging
- [ ] Windows installer/portable build of the desktop app, first-run model download, update mechanism for data snapshots

## Discovered tasks
- [ ] Symlink test in `tests/test_paths.py` is skipped on this machine (needs privilege); run it once elevated or via Developer Mode
- [ ] Optional hardening: reject allowlisted hosts that resolve to private/loopback IPs (DNS-rebinding style); not yet implemented
- [ ] Ask Enka maintainer (Discord) about third-party use/attribution; HoYoverse fan-content applicability to Genshin is OPEN
- [ ] Sign/verify strategy for pinned upstream commit SHAs (record in snapshot manifest)

- [ ] genshin-db ingestion (pinned tag) for set 2pc/4pc text and per-item "added in version"; Enka sets only carry numeric AddProps
- [ ] `prop_names` is data-derived and incomplete (e.g. elemental DMG ids 40-46 are indistinguishable by value); weapon secondary stats and character base props keep upstream numeric ids until a source names them
- [ ] Per-fact confidence (currently per dataset); Amber responses are unpinned (latest only), so Amber hashes are recorded but cannot be replayed
- [ ] Scheduled/automatic sync and "check for newer pinned SHA" flow (GitHub API is rate limited to 60/h unauthenticated; `git ls-remote` was used by hand to resolve the pin)
- [ ] Decide what `verified` means operationally once Ben supplies hand-checked artifacts (currently never set automatically)

- [x] (superseded) Stat priorities: Ben observed the game highlights recommended substats per character (e.g. Vesna: CRIT DMG, ATK, EM, CRIT Rate). Not found in Enka store, Enka showcase or Amber character data. Find where the client exposes it (needs datamine; legal posture unclear) or curate profiles with Ben
- [ ] Re-sync is required after `SCHEMA_VERSION` bumps (now 2: `SubstatTier.affix_id`)

- [x] Curated profile format (`builds/profiles.py`, `profiles/characters.toml`, `genshin-companion profiles`); Vesna recorded (substats only). The in-game recommendation is usage statistics from recently active players, shown by the game as sets + main affixes + highlighted substats; most likely server-side, so datamining would probably not find it. Decision: curate with Ben (no datamining)
- [x] Ben supplied the in-game table (Best in Slot, Favoured Minor Affixes, and Favoured Main Affixes for sands/goblet/circlet with the game's usage percentages; 28 characters incl. all 12 he owns). Stored as 28 `kind = "in-game"` `provisional` profiles. Verified three ways: image readings by me plus 12 blind readers, a round-trip of the loaded TOML, and finally an exact cell-by-cell comparison with his own `Genshin Characters.xlsx` (784 cells, 0 differences). Still missing from the game: recommended weapons
- [x] Ben decided against reading the game client/traffic for recommendations (terms and account risk); instead he screenshots the in-game recommendation screens himself into `data-home/screenshots/` (gitignored) and I transcribe them for his confirmation. Add a `recommended_weapons` field (validated against the snapshot) when that data arrives
- [x] Guide-site sheet from a friend (`Genshin_Artifact_Stat_Priorities.xlsx`, 2026-11-08) stored as 10 `provisional` ordered-tier profiles in `profiles/characters.toml` (Mitya, Nilou, Qiqi, Illuga, Dahlia, Chevreuse, Mika, Candace, Fischl, Yanfei; none on Ben's roster). Ben chose "ordered tiers": the format keeps the source ranking, conditions and sets, and stores NO invented weights. Cross-checked against the sheet cells by script plus 5 independent reviewers
- [x] Ben confirmed the order of the four favoured substats means nothing (one tie tier is right). Mika and Dahlia have both an in-game and a guide profile that disagree; scoring prefers in-game
- [ ] Scoring rule that turns `substat_tiers` into weights (one documented rule, tuned with Ben); conditional stats (`only with Favonius Lance`, `only up to the ER target`) default to weight 0 until Ben decides; ER/EM/HP targets are only free-text notes so far
- [ ] `validate_profiles` cannot check a main stat is legal for its slot (snapshot main stats carry no slot). Needs equip-type to main-stat pools from data, not memory
- [x] Recommended weapons researched online (the game has none): 2 rounds, 26 research agents, every cited claim re-checked against the live page by a second agent (511 supported, 13 flagged and excluded). `recommended_weapons` added to the format (name, tier, sources with url/accessed/as_of/rank), 135 options across the 28 in-game profiles, names checked against the snapshot and weapon type against the character. Awaiting Ben's review before commit
- [ ] Weapon-type check inside `validate_profiles` needs a data-sourced weapon-type map (the generator used one derived from Ben's roster; the snapshot itself does not pair character and weapon type names with ints)
- [ ] Weapons for the 8 guide-only characters (Mitya, Nilou, Qiqi, Illuga, Candace, Fischl, Yanfei, Chevreuse) are not researched; 16 cited pages are stale and 4 undated (kept visible, never counted towards `best`)
- [ ] Data for characters beyond the 28: searched 2026-11-08. Only lead is Prydwen.gg per-character WEAPON usage percentages (from Enka-connected profiles, large samples, refreshed ~07 Nov 2026); it blocks automated fetches (HTTP 403, terms page unreadable; robots.txt allows character pages, crawl-delay 10), so NOT fetched or worked around. No public source found for main-stat/substat percentages; HoYoLAB wiki recommendations are the same HoYoverse data but scraping is barred by their ToS. Best path: ask the friend with the guide sheet for the same in-game table for their characters (covers the 8 guide-only ones); Ben may screenshot a few Prydwen pages by hand
- [ ] Imported pieces are mostly low rarity/level: golden fixtures from Ben's own account will be weak; consider more mature artifacts (Enka's documented example account verified the roll maths on 20 five-star pieces)

## Decisions made
- Toolchain: uv (installed via pip --user), task runner is `tasks.py` (no make)
- Obsidian vault: `C:\Users\bodro\OneDrive\Documents\VisionVault`
- UI: small desktop app (chat, team comps, artifact recommendations, Genshin-inspired style). Built as a local web UI first, desktop shell wrapped around it later.

## Open questions for Ben
- Desktop shell choice after the spike (Tauri + Python sidecar vs. alternatives)
- Whether the app should ever be distributed publicly (affects asset and licensing choices)
