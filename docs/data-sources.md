# Data sources: research notes (read 2026-11-08)

Findings come from reading each source's current docs, licence files and live responses on
2026-11-08, then having a second agent try to refute the licence/terms claims. Some pages are
JavaScript-rendered and were read through a summarising fetch tool, so wording is paraphrase unless
marked verbatim. **Nothing here is legal advice; items marked OPEN need a human decision.**

## Summary table

| Source | Code licence | Data licence / terms | Roll tiers? | Pinnable? | Verdict |
|---|---|---|---|---|---|
| Enka.Network UID API (`enka.network/api/uid/{uid}`) | n/a | No ToS found; usage rules in API docs only | n/a | no (live API) | Use for Phase 3 import |
| Enka `store/` files (`EnkaNetwork/API-docs`) | **none** (`license: null`, no LICENSE file) | all rights reserved by default; derived from datamine | **yes** (`store/gi/affixes.json`) | commit SHA only (no tags/releases) | Fetch at runtime into local cache; never vendor |
| genshin-db (`theBowja/genshin-db`) | MIT | no separate data licence; author: "Currently using MIT License but I don't really care" | **no** | git tags per patch (e.g. `v5.2.16` = 7.2) | Names, sets, descriptions, version metadata; Node-oriented, large |
| Project Amber (`gi.yatta.moe`, formerly Ambr.top) | n/a | **no terms, no data licence**; fan site, ad-funded | yes (`/api/v2/static/reliquaryCurve`) | **no** (latest only) | Secondary cross-check only; fragile |
| Genshin Optimizer (`frzyc/genshin-optimizer`) | MIT | values derive from the datamine | yes (`libs/gi/stats/Data/Artifacts/artifact_sub.json`, `artifact_main.json`) | commit SHA | Test oracle / third cross-check, not a runtime dependency |
| Dimbreath datamine | none | HoYoverse content; legal posture uncertain (`AnimeGameData` GitHub repo returns 404; reported takedown, unverified) | yes (raw Excel) | commit SHA | Do not depend on |

## Enka.Network UID API
- Endpoint: `GET https://enka.network/api/uid/{uid}/` (full showcase) and `?info` (player info only,
  much faster). Icons at `https://enka.network/ui/{icon}.png`.
- Rules from the API docs: set a **custom User-Agent**; no published rate limits (dynamic; slower
  responses, then **HTTP 429**); **do not enumerate UIDs**; every response carries `ttl` (seconds):
  cache for that long, repeat requests inside the TTL still count against the limit.
- Status codes: 400 bad UID format, 404 player not found, 424 maintenance / broken after update, 429
  rate limited, 500/503 server errors. **There is no dedicated "private showcase" code**: a 200
  without `avatarInfoList` means closed/empty showcase.
- No ToS page exists (`/terms` is 404); the privacy policy is JS-rendered and its text was not read.
  OPEN: ask the maintainer (Discord, linked in the site footer) if a public fan tool is welcome and
  whether they want attribution. Add courtesy attribution regardless.
- Status page notes an upstream limit introduced in 5.1 that can degrade third-party tools.
- The UID is part of the request URL. This is the one unavoidable exception to "no user content
  leaves the machine" and must stay documented in README and the UI.

## Enka store files
- Repo `EnkaNetwork/API-docs`, active (pushed 2026-11-05), shared with HSR/ZZZ/Endfield. Automated
  "KitDump Bot" commits roughly twice a week plus manual fixes. **No releases, no tags**: pin by
  commit SHA via `raw.githubusercontent.com/EnkaNetwork/API-docs/<sha>/store/gi/...`.
- Two layouts exist (legacy root `store/*.json` and newer `store/gi/*.json`) with different field
  names and icon conventions (bare names vs `/ui/...png` paths); a 2026-09-28 commit restructured
  them. Validate with strict schemas; expect `{}` placeholder entries.
- `store/gi/affixes.json` maps six-digit affix IDs to `{PropType, Position, Value, Efficiency}`.
  Semantics (tier position, whether `Value` is the per-roll value) are **not documented** and must be
  checked against another source and in-game artifacts before being trusted.
- No licence: **do not commit these files to a public repo**; the app fetches them at runtime into
  the user's local snapshot.

## genshin-db
- Active; a release per game patch (6.4 to 7.2 in about nine months); single maintainer; npm can lag
  GitHub by a patch. The release title carries the game version; `src/data/version/*.json` records
  which version each item was added in.
- Contains characters, weapons, artifact sets (names, 2pc/4pc text) and so on. **It has no substat
  roll tiers or main-stat curves** in the files inspected.
- Full package is ~188 MB unpacked across 15 languages; fetch only needed folders from a pinned tag.
  No Python port found; JSON files must be read directly.

## Project Amber / Ambr.top
- `ambr.top` 301-redirects to `gi.yatta.moe`; `api.ambr.top` no longer resolves. Undocumented
  `/api/v2/...` routes read from the site's JS; no terms, no rate limits documented; Python's default
  User-Agent got a 403 (a descriptive UA works). Latest data only: no version pin; keep our own
  snapshot. `reliquaryCurve` has `affix` (per rarity, per stat, ascending arrays) plus `initial` and
  `ranked` (main-stat scaling).
- Treat all text from this site as untrusted data like any other download.

## Genshin Optimizer
- MIT. Its `artifact_sub.json` and `artifact_main.json` give per-rarity substat values and main-stat
  curves; it ships a correction file, showing even they patch extracted values. Good oracle for
  cross-checking our snapshot; not a runtime source.

## HoYoverse fan-content rules
- No Genshin-specific Fan Creations Guide was found. The Honkai: Star Rail guide (v1.0, 2023) allows
  non-commercial fan works with a copyright notice and non-affiliation statement and requires
  authorisation for merchandise at volume. Whether it applies to Genshin, or to a tool that fetches
  icons at runtime, is **OPEN**. Mitigations already in the design: no bundled art, non-commercial,
  clear "unofficial fan tool" disclaimer.

## Recommended Phase 1 plan (awaiting Ben's decision)
1. Primary: Enka `store/gi/*` pinned by commit SHA (characters, weapons, relic sets, affixes,
   relic levels) because it matches Enka showcase IDs 1:1.
2. Independent cross-check for roll tiers and main-stat curves: Project Amber `reliquaryCurve`,
   with disagreements marking the affected facts `provisional`. Genshin Optimizer data as an
   offline test oracle only.
3. genshin-db (pinned tag) for set bonus text, descriptions and per-item "added in version".
4. Allowlist (initial): `enka.network`, `raw.githubusercontent.com`, `gi.yatta.moe`.
