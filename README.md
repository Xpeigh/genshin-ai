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
(`genshin-companion import --file PATH`) and the app will not contact Enka at all.

### Importing characters: what it can and cannot do, and why there is no login
- **No login, ever.** This app never asks for your HoYoverse/miHoYo account, password, cookies or
  tokens, and never reads game files, memory or network traffic. It only reads the **public
  Character Showcase** of the UID you give it, through Enka.Network. Importing a whole account would
  need your login, which would put your account at risk, so it is deliberately not offered.
- **Only showcased characters can be imported.** Add the characters you want to the in-game
  Character Showcase and keep it public; a closed or empty showcase imports nothing.
- **One UID at a time.** Enka asks tools not to scan many UIDs, and so does this one. Responses are
  reused for the time Enka states, so `import --refresh` and repeated commands do not hit Enka again
  until that window is over.
- **Only share a friend's UID with their OK.** It is sent to enka.network exactly like yours.
- **Unofficial.** This is a fan tool, not affiliated with or endorsed by HoYoverse or Enka.Network.

Useful commands: `genshin-companion lookup <uid>` previews a player's showcase without saving
anything; `genshin-companion import <uid>` saves it; `genshin-companion import --refresh` updates
every saved roster when Enka's reuse window has passed.

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
