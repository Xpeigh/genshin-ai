# Genshin Companion

A local-first, **unofficial** fan tool for Genshin Impact: import a roster, score artifacts and
weapons, get build recommendations, ask lore questions. It is not affiliated with, endorsed by or
connected to HoYoverse / Cognosphere. Status: early development (data layer and security
foundations; no user-facing features yet).

## What this app sends over the network, and what it does not

**Everything stays on your computer** (UID, roster, scores, chat history, settings). There is no
telemetry, analytics, crash reporting or account system.

The app only ever makes **HTTPS `GET` (and `HEAD`) requests** to a short list of websites, through
one piece of code (`src/genshin_companion/net/client.py`). It never uploads anything: no request
bodies, no cookies, no credentials. A test fails the build if any other part of the program tries
to use the network. Run `genshin-companion net-policy` to see the exact list of allowed hosts.

| Purpose | Host | What is sent |
|---|---|---|
| Fetch public game data | listed by `net-policy` | the file path only |
| Import your roster | `enka.network` (when enabled) | **your UID, as part of the request URL**; unavoidable, because that is how the lookup works |

If you do not want your UID to leave your machine, import a roster from a local file instead
(planned) and the app will not contact Enka at all.

Downloaded game data is treated as untrusted: it is schema-checked and sanity-checked in a
quarantine area before use, the previous good copy is kept, and nothing downloaded is ever executed.

### Your data on disk
`genshin-companion paths` shows where files live. `genshin-companion clear-data --yes` deletes your
rosters, chat history, settings, caches and logs (`--include-game-data` also removes downloaded game
data).

## Development (Windows)

```
python -m pip install --user uv
python -m uv sync
python -m uv run python tasks.py check     # lint, types, tests, dependency audit
```

The dependency audit contacts PyPI/OSV; that is development tooling, not part of the shipped app.
See `SPEC.md`, `CLAUDE.md` and `docs/data-sources.md`.
