# SPEC: Genshin Companion

## Goals
1. Import a player's roster by UID and score artifacts and weapons.
2. Recommend builds, stat priorities, and weapons per character.
3. Answer lore and "how does X work" questions with sources.
4. Stay current with patches automatically, and be honest when data is stale or provisional.
5. Run locally on modest hardware (small model, no cloud dependency required).

## Hard rules (copy into CLAUDE.md)
- **The LLM never produces game numbers from memory.** Every stat, weight, multiplier, and recommendation comes from a tool result backed by the data snapshot.
- **The scoring engine is deterministic and LLM-free.** Same input plus same data version gives the same output. No network and no model imports in that package.
- **Game data is never hardcoded from memory.** Roll tiers, base stats, and set bonuses come from the synced snapshot. The sanity values below are test hints only and must be verified against the data.
- **Every recommendation carries provenance:** `source`, `data_version`, `confidence` (`verified` | `curated` | `provisional`).
- **No live network calls in tests.** Use recorded fixtures.
- Respect third-party terms: descriptive User-Agent for Enka, honor cache TTLs, no aggressive scraping.
- **Local-only and GET-only.** User data never leaves the machine. All network access goes through one allowlisted, GET-only HTTPS client. See "Security and privacy".
- **Downloaded data is untrusted** until validated. Quarantine, schema-check, diff-check, keep last-known-good.

## Module boundaries
```
genshin_companion/
  data/        # sync, snapshot models, changelog diffing
  scoring/     # PURE library: artifacts, weapons, stat profiles
  enka/        # UID import client + payload mapping
  builds/      # curated profiles + recommendation assembly
  teams/       # offline analyzer (separate CLI, writes JSON)
  chat/        # Ollama wrapper, tool definitions, guardrails
  lore/        # ingestion + retrieval
  app/         # UI shell (CLI first)
tests/
  fixtures/    # enka payloads, golden artifacts
```
Dependency direction: `app -> chat -> (builds, scoring, lore, data)`; `scoring` depends only on data models.

## Scoring engine

### Inputs
- Artifact: slot, set, rarity, level, main stat, substats with rolled values (and roll counts if available).
- Character context: stat-weight profile (per character and role), recommended main stats per slot, desired sets.
- Data snapshot: substat roll tiers and maximum values.

### Outputs
- Per-piece: main-stat fit, set fit, weighted roll score, crit value, "% of theoretical maximum", and for unleveled pieces a potential range.
- Per-character: total build score, weakest slot, suggested upgrade targets.
- Explainability: each score returns the breakdown that produced it, so the chat layer can quote it and tests can assert on it.

### Methods
- **Crit value:** `CR*2 + CD` as the baseline summary metric.
- **Weighted roll value:** each substat's contribution is its rolled value divided by the max single-roll value, multiplied by the profile weight for that stat. Weights live in a versioned data file.
- **Potential:** for pieces below max level, estimate the achievable range from remaining upgrades (documented method; do not present a single point estimate as certain).
- Sanity hints for the five-star max single-roll values (verify against the snapshot, do not hardcode): ATK% and HP% are about 5.83, DEF% about 7.29, Energy Recharge about 6.48, Crit Rate about 3.89, Crit DMG about 7.77, Elemental Mastery about 23.3, flat ATK about 19.5.

### Weapon scoring
- Phase 2 baseline: base ATK, secondary stat fit with the character's profile, refinement level.
- Passive effects are scored via curated tags per character (e.g. "buffs team ATK", "on-field DPS only"), not by free-form reasoning. A proper damage model is Phase 8.

### Golden tests
Ask Ben for 5-10 real artifacts with scores he has verified by hand. Store as fixtures. A scoring change that breaks a golden test needs an explicit, documented reason.

## Enka import
- Read the current API docs before coding; do not rely on memory for endpoint shapes.
- Descriptive User-Agent, honor TTL from the response, cache on disk, handle: private showcase, character details hidden, rate limiting, maintenance.
- Map payloads to internal models in one place (`enka/mapping.py`) so API changes touch one file.
- Showcase shows only a subset of characters; the UI must say so.

## Data sync and freshness
- Snapshot = directory or SQLite file stamped with `game_version`, `fetched_at`, per-source hashes.
- `sync` diffs against the previous snapshot and writes a changelog (new characters, changed weapons, changed sets).
- New characters or changed kits are `provisional` until a curated profile exists.

## Chat layer
- Target: a small local model (about 3-4B class) via Ollama so it runs on modest hardware. Pick by benchmark, not by name: tool-call reliability, refusing to guess, and instruction-following matter more than raw knowledge.
- Prompt design: the model is a narrator of tool results. System prompt states that unsupported claims are not allowed.
- Always include `data_version` and confidence in answers that depend on game data.

## Team analyzer (Phase 8, offline)
- Runs on Ben's PC, writes versioned JSON (`team_rankings.json`) with assumptions: enemy model, rotation template, character investment level, patch version.
- Enumerate by role slots (main DPS, sub-DPS, buffer, healer/shielder), not raw 4-combinations.
- Rotation templates are a documented, small set. Results are rankings under stated assumptions, not "the truth".
- The app reads the JSON and never runs the analysis itself.

### Simulation scope and validation
- **No LLM runs the simulations.** They are deterministic code. A larger local model (Ben's PC has 16 GB VRAM) is useful at development time for drafting kit modules and summarizing results, but it is never the source of truth. Ground truth is in-game measurement.
- **Do not grid-search everything.** Levels, constellations, weapons and artifact sets are swept with pruning (see plan.md, Phase 8e). The effort that matters is kit correctness per character, not raw compute. Raw evaluation is cheap, so a pruned sweep fits in hours on one PC.
- **Coverage tiers.** Characters are added in priority order. A character with no validated kit module appears in rankings only as `provisional`, or not at all.
- **Validation gate (layered).** A kit module is `validated` only when it passes every layer that applies: (1) the formula layer reproduces about 20-30 in-game readings recorded by Ben within a stated tolerance; (2) automated cross-checks against established open calculators agree across a large set of configurations; (3) new characters and any disagreements get fresh in-game readings. Ask Ben for fixtures; never invent expected values. Reference calculators are test oracles, not ground truth, and their licenses and terms must be checked before use.
- **Hands off the game.** Never automate game inputs, read game memory, or modify the game client. Those violate the game's terms and put Ben's account at risk. The only permitted experiment is passive screen capture with number recognition, built last and only after reading the current terms.
- **Disagreement policy.** Where our results differ from community consensus or other calculators, surface both and explain the cause.

## User interface
- **Target:** a small Windows desktop app with a chat panel, a team-comps view, and an artifact/weapon recommendations view, styled in a Genshin-inspired look.
- **Architecture:** Python core, a local HTTP API (FastAPI or similar), and a web front end that talks to it. The UI must work in a normal browser first. The desktop shell (leading candidate: Tauri with a bundled Python sidecar) is a thin wrapper added afterwards, so the shell stays swappable.
- **Consistency rule:** the CLI and the UI call the same API; no logic lives in the front end beyond presentation.
- **Visual style:** original design inspired by the game's feel (warm parchment tones, gold accents, ornate dividers, element colours). Build it with CSS and original or properly licensed assets.
- **Asset note:** do not bundle ripped game art, logos or audio. Fetch icons at runtime from the data sources that serve them, and check HoYoverse's fan-content guidelines and each source's terms before any public distribution. Flag any concern to Ben.
- **Honesty in the UI:** show `data_version` and the confidence label next to every recommendation, and say plainly when the Enka showcase only exposes some characters.

## Security and privacy
Intended for eventual public sharing under the Xpeigh handle, so these are requirements, not nice-to-haves.

### Local-only data
- All user data (UID, roster, scores, chat history, settings) stays on the user's machine. No telemetry, analytics, crash reporting or accounts. No outbound request ever contains user content.
- Be honest about the one unavoidable exception: fetching a roster means the UID is sent to Enka as part of a GET request. Document this in the UI and README, and let the user opt out by importing from a local file instead.
- Do not log UIDs or chat contents beyond local, user-clearable files.

### GET-only, allowlisted networking
- All outbound traffic goes through one HTTP client module. It permits only `GET` (and `HEAD`), only HTTPS, only to an explicit domain allowlist in config, with timeouts, size caps, and a redirect policy that stays inside the allowlist.
- No other module may import an HTTP library directly. Enforce with a lint rule or a test that scans imports, so the guarantee cannot rot.
- No request bodies, no uploads, no cookies or credentials sent, descriptive User-Agent with no personal data.
- The chat model has no network tool, no file-write tool and no shell tool. Its tools are read-only lookups against local data.

### Reliability checks on downloaded data
- Treat everything downloaded as untrusted input. Never execute it, never `eval`, never unpickle. Parse JSON against strict schemas and reject unknown or oversized structures.
- New snapshots go into quarantine first. Validate: schema, sanity ranges (e.g. no negative stats), and a diff-size check against the last-known-good snapshot. A suspiciously large change is held for review instead of applied.
- Cross-check key facts across two independent sources where possible, and mark disagreements `provisional`.
- Keep the last-known-good snapshot and support one-command rollback. Record source URL, fetch time and content hash for every file.
- Where a source publishes versioned releases, prefer pinned versions or commit hashes over "latest".

### Prompt-injection defense
- Patch notes, wiki pages and lore text are untrusted and could contain instructions aimed at an LLM. Ingested text is only ever placed in the model's context as clearly delimited quoted data, never in the system prompt, and the model is told that quoted data is never instructions.
- Because the model's tools are read-only and local, an injection can at worst produce a wrong answer, not an action. Keep it that way.
- LLM-assisted patch parsing outputs structured diffs that are schema-validated and flagged for human review before they affect recommendations.

### Local API and desktop shell
- Bind the local API to `127.0.0.1` only. Require a per-launch random token, reject unexpected `Host` and `Origin` headers, and set no permissive CORS. This stops other local pages from talking to the app (DNS-rebinding and cross-site requests).
- Desktop shell: strict Content-Security-Policy, no remote code loading, minimal permissions, no arbitrary filesystem or shell access exposed to the web layer.

### Supply chain and distribution
- Pin dependencies with hashes (lock file) and run a dependency audit in `make check`.
- Model downloads: pin the exact model name and digest, verify after download.
- Releases: code-signed installers if feasible, published checksums, and a plain-language README stating what the app does and does not send over the network.
- Make clear in the UI and README that this is an unofficial fan tool, not affiliated with HoYoverse.

## Non-obvious architectural decisions (flag in every handoff)
1. Scoring engine is separate from and independent of the LLM.
2. Heavy team analysis is offline and produces a static artifact the app consumes.
3. Confidence labels are first-class data, not decoration.
4. Curated stat-weight profiles are a deliberate human-in-the-loop component; automation proposes, a human approves for new characters.
5. Greenfield repo, independent of the Elite Dangerous assistant; only generic helpers (e.g. the Ollama wrapper) may be copied, not shared.
6. UI is a browser-first web front end over a local API, with the desktop shell added last, so the shell choice can change without touching the app.
7. Game icons and art are fetched at runtime and never bundled, to avoid redistributing someone else's assets.
8. A single GET-only, allowlisted HTTP client is the only way out of the process, and a test enforces that no other module does networking.
9. Ingested web text is treated as hostile to the LLM (prompt injection): quoted data only, read-only local tools, and no tool that can write, run or send anything.
10. Each user's app talks to Enka directly with its own cache and no central server, which keeps data local and spreads load.
11. Rankings come from validated simulation modules with a hard validation gate, not from scraped tier lists. Unvalidated characters are shown as `provisional`.
12. The simulation is pruned and tiered on purpose; exhaustive sweeps over every variable were considered and rejected as infeasible and redundant.
