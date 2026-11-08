# Kickoff prompt for Claude Code

Paste everything below the line into a fresh Claude Code session in the new, empty repo. Put `SPEC.md` in the repo root and `plan.md` in `.claude/` first.

---

Hi! I'm Ben, and I'm really glad to be building this with you. We're making a local-first Genshin Impact companion: you import a player's roster by UID, score their artifacts and weapons, get build and stat-priority recommendations, and ask lore questions, all running on a small local model so almost anyone can use it on modest hardware.

Please start by reading `SPEC.md` and `.claude/plan.md` carefully. They hold the architecture and the order of work. Two things matter most to me:

1. **Trustworthiness over cleverness.** The scoring engine must be deterministic and must never involve an LLM. The chat model only phrases results that tools hand to it, and it should say "I don't know" rather than guess. Game data should come from the synced snapshot, never from your memory or mine, since both can be out of date.
2. **Honesty about freshness.** Anything that depends on a patch should carry a data version and a confidence label.

How I'd like to work:
- Security is a core requirement, because I may share this app publicly later. All user data stays on the user's machine, and the only network traffic is GET requests to an allowlisted set of domains, through one HTTP client module. Everything downloaded is treated as untrusted and validated before use. Please read the "Security and privacy" section of SPEC.md closely and build Phase 0b before writing any network code.
- Begin with Phase 0, Phase 0b and Phase 1, then stop and show me what you built before moving on. If anything in the spec is unclear or seems wrong, please ask me rather than guess. I'd much rather answer a question than untangle an assumption.
- Before using any external source or API (Enka, genshin-db, Ambr, patch notes), read its current docs and terms, and tell me about any licensing or rate-limit concerns you find.
- For golden tests of the scoring engine, ask me for real artifacts that I've checked by hand. Please don't invent expected values.
- Keep `.claude/plan.md` up to date as you work (tick items off, add new tasks as you discover them).
- At the end of each session, write `.claude/handoff-YYYY-MM-DD.md` with: what was completed, next steps in order, affected files, open issues, and a section called **Non-obvious decisions** that explicitly flags any architectural choice a future reader wouldn't guess from the code.
- Obsidian vault path for notes: `C:\Users\bodro\OneDrive\Documents\VisionVault`. Please append a dated entry to that vault's Daily Note (`Daily Notes/YYYY-MM-DD.md`) for each change, and keep a project note for this app there, linked with [[wikilinks]]. Search the vault for existing notes before creating new ones.
- The final product is a small desktop app (chat, team comps, artifact recommendations, in a Genshin-inspired look). See "User interface" in SPEC.md. We build the backend and a CLI first, so the UI comes later and doesn't need your attention yet.

Thank you! Take your time, and please tell me early if a part of the plan doesn't survive contact with reality.
