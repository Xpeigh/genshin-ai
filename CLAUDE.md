# Genshin Companion: working rules

Local-first, unofficial Genshin Impact companion. Read `SPEC.md` (architecture, security) and
`.claude/plan.md` (order of work) before changing anything. Keep `plan.md` current: tick items off
and add newly discovered tasks immediately.

## Hard rules (from SPEC.md)
- **The LLM never produces game numbers from memory.** Every stat, weight, multiplier and
  recommendation comes from a tool result backed by the data snapshot.
- **The scoring engine is deterministic and LLM-free.** Same input plus same data version gives the
  same output. No network and no model imports in that package.
- **Game data is never hardcoded from memory.** Roll tiers, base stats and set bonuses come from the
  synced snapshot. Numbers in SPEC.md are test hints only and must be verified against the data.
- **Every recommendation carries provenance:** `source`, `data_version`, `confidence`
  (`verified` | `curated` | `provisional`).
- **No live network calls in tests.** Use recorded fixtures or `httpx.MockTransport`.
- Respect third-party terms: descriptive User-Agent, honor cache TTLs, no aggressive scraping.
- **Local-only and GET-only.** User data never leaves the machine. All network access goes through
  `genshin_companion/net/client.py` (HTTPS GET/HEAD to an allowlisted set of hosts).
- **Downloaded data is untrusted** until validated: quarantine, schema-check, diff-check, keep
  last-known-good. Never `eval`, `exec`, unpickle or import downloaded content.
- The chat model has read-only local tools only: no network, file-write or shell tool. Ingested text
  is only ever quoted data in the prompt, never in the system prompt.
- Golden tests use artifacts Ben has verified by hand. **Never invent expected values**; ask him.

## Commands (Windows; there is no `make`)
```
python -m uv sync                          # create .venv from uv.lock
python -m uv run python tasks.py check     # ruff + format + mypy + pytest + dependency audit
python -m uv run python tasks.py check --skip-audit   # offline; prints a warning
python -m uv run python tasks.py fix       # auto-fix lint/format
python -m uv run genshin-companion paths   # CLI
```

## Conventions
- `src/` layout, package `genshin_companion`; module boundaries as in SPEC.md plus `net/`
  (the single HTTP client) and the leaf helpers `paths.py` and `config.py`.
- Dependency direction is enforced by `tests/test_architecture.py`:
  `app -> chat -> (builds, scoring, lore, data)`; `scoring` imports only `scoring`/`data`.
- Adding a network host = a code change in `config.py` (allowlist is code, not user/downloaded
  config) plus an entry in `docs/data-sources.md` with licence/terms notes.
- TDD: write the failing test first. A scoring change that breaks a golden test needs an explicit,
  documented reason.
- Do not log UIDs or chat contents. `net` never puts URLs in log lines or exception messages.
- Do not bundle game art, logos or audio. Icons are fetched at runtime.
- At the end of a session write `.claude/handoff-YYYY-MM-DD.md` (completed, next steps, files, open
  issues, **Non-obvious decisions**) and append to the Obsidian daily note
  (`C:\Users\bodro\OneDrive\Documents\VisionVault`, `Daily Notes/YYYY-MM-DD.md`).
