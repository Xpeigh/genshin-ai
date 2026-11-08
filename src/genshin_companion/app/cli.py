"""Command-line entry point. Thin: real work lives in the library packages."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from genshin_companion import __version__
from genshin_companion.app.report import render_profile, render_roster
from genshin_companion.app.score import render_scores, score_roster
from genshin_companion.builds.profiles import (
    CharacterProfile,
    ProfileError,
    load_profiles,
    validate_profiles,
)
from genshin_companion.config import default_network_policy
from genshin_companion.data import sources
from genshin_companion.data.changelog import diff, render
from genshin_companion.data.models import Snapshot
from genshin_companion.data.store import SnapshotStore, StoreError
from genshin_companion.data.sync import run_sync
from genshin_companion.enka.client import EnkaError, EnkaRateLimitedError, fetch_roster
from genshin_companion.enka.mapping import EnkaFormatError, parse_showcase
from genshin_companion.enka.models import Roster
from genshin_companion.net import NetworkError, SafeHttpClient
from genshin_companion.paths import (
    DataDirError,
    DataLayout,
    clear_user_data,
    ensure_layout,
    resolve_home,
)

# Tests inject a client built on a mock transport; production code leaves this as None.
_client_override: SafeHttpClient | None = None


def _cmd_paths(_: argparse.Namespace) -> int:
    layout = DataLayout(resolve_home())
    print(f"home:       {layout.root}")
    print(f"user data:  {layout.user}   (rosters, chat, settings)")
    print(f"cache:      {layout.cache}   (HTTP cache; contains rosters)")
    print(f"logs:       {layout.logs}")
    print(f"snapshots:  {layout.snapshots}   (public game data)")
    print(f"quarantine: {layout.quarantine}   (downloads awaiting validation)")
    return 0


def _cmd_net_policy(_: argparse.Namespace) -> int:
    p = default_network_policy()
    print("Outbound traffic: HTTPS GET/HEAD only, no bodies, no cookies, no credentials.")
    print("Allowed hosts (exact match):")
    for host in sorted(p.allowed_hosts) or ["(none configured yet)"]:
        print(f"  - {host}")
    print(
        f"Limits: default {p.default_max_bytes} B, hard {p.hard_max_bytes} B per response; "
        f"{p.max_redirects} redirects max; {p.total_timeout}s total."
    )
    print(f"User-Agent: {p.user_agent}")
    return 0


def _cmd_clear_data(args: argparse.Namespace) -> int:
    root = resolve_home()
    if not args.yes:
        print(
            f"This deletes your imported rosters, chat history, settings, caches and logs under "
            f"{root}.\nRe-run with --yes to confirm (add --include-game-data to also delete "
            f"downloaded game data).",
            file=sys.stderr,
        )
        return 2
    if not root.exists():
        print("Nothing to delete: no data directory exists.")
        return 0
    try:
        removed = clear_user_data(DataLayout(root), include_game_data=args.include_game_data)
    except DataDirError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    print(f"Removed {len(removed)} item(s) from {root}.")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    layout = ensure_layout(resolve_home())
    ref = "master" if args.latest else sources.ENKA_PINNED_REF
    if args.latest:
        print(
            "WARNING: --latest fetches an unpinned branch; the result is validated and "
            "diff-checked, but review the changelog.",
            file=sys.stderr,
        )
    client = _client_override or SafeHttpClient(default_network_policy())
    try:
        result = run_sync(
            layout,
            client,
            now=datetime.now(UTC).replace(microsecond=0),
            ref=ref,
            allow_single_source=args.allow_single_source,
            accept_held=args.accept_held,
        )
    finally:
        if _client_override is None:
            client.close()
    print(f"{result.status}: {result.message}")
    if result.report is not None:
        for line in (*result.report.warnings, *result.report.review_reasons, *result.report.errors):
            print(f"  - {line}")
    if result.staged is not None:
        print(f"  candidate kept in quarantine: {result.staged}")
    return 0 if result.status in {"promoted", "unchanged"} else 1


def _save_roster(layout: DataLayout, roster: Roster) -> Path:
    target = layout.user / "rosters"
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{roster.uid}.json"
    path.write_text(roster.model_dump_json(indent=2), encoding="utf-8")
    return path


def _current_snapshot(layout: DataLayout) -> Snapshot | None:
    try:
        return SnapshotStore(layout).current()
    except StoreError:
        return None


def _cmd_import(args: argparse.Namespace) -> int:
    layout = ensure_layout(resolve_home())
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        if args.file:
            body = Path(args.file).read_bytes()
            if len(body) > 4 * 1024 * 1024:
                print("Refused: file is larger than 4 MiB.", file=sys.stderr)
                return 1
            roster = parse_showcase(body, fetched_at=now, source="file")
            how = "imported from a local file; nothing was sent over the network"
        elif args.uid:
            print(
                "Note: importing from Enka sends this UID to enka.network in the request URL. "
                "Use --file to import a saved response instead.",
                file=sys.stderr,
            )
            client = _client_override or SafeHttpClient(default_network_policy())
            try:
                result = fetch_roster(args.uid, client, layout.cache, now)
            finally:
                if _client_override is None:
                    client.close()
            roster = result.roster
            how = (
                f"served from the local cache; next request in {result.seconds_until_refresh}s"
                if result.from_cache
                else "fetched from Enka and cached for its ttl"
            )
        else:
            print("Give a UID or --file PATH.", file=sys.stderr)
            return 2
    except EnkaRateLimitedError as exc:
        wait = f" Retry after {exc.retry_after}s." if exc.retry_after else ""
        print(f"Rate limited.{wait}", file=sys.stderr)
        return 1
    except (EnkaError, EnkaFormatError, NetworkError, OSError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    path = _save_roster(layout, roster)
    print(f"Imported {len(roster.characters)} character(s); {how}.")
    print(f"Saved to {path}")
    print(render_roster(roster, _current_snapshot(layout)))
    return 0


def _load_roster(layout: DataLayout, uid: str | None) -> tuple[Roster | None, int]:
    """The one saved roster (or the one named by ``uid``), or an error exit code."""
    folder = layout.user / "rosters"
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if uid:
        files = [f for f in files if f.stem == uid]
    if not files:
        print("No imported roster. Run: genshin-companion import <uid>", file=sys.stderr)
        return None, 1
    if len(files) > 1:
        print(
            "Several rosters saved; pass a UID: " + ", ".join(f.stem for f in files),
            file=sys.stderr,
        )
        return None, 2
    try:
        return Roster.model_validate_json(files[0].read_text(encoding="utf-8")), 0
    except (ValidationError, UnicodeDecodeError, OSError):
        print(
            "The saved roster could not be read. Import it again: genshin-companion import <uid>",
            file=sys.stderr,
        )
        return None, 1


def _cmd_roster(args: argparse.Namespace) -> int:
    layout = DataLayout(resolve_home())
    roster, code = _load_roster(layout, args.uid)
    if roster is None:
        return code
    print(render_roster(roster, _current_snapshot(layout)))
    return 0


MAX_PROFILE_FILE_BYTES = 1_000_000


def _read_profiles(path: Path) -> list[CharacterProfile] | None:
    """Load a profile file, printing the reason and returning None if it cannot be used."""
    if not path.is_file():
        print(f"No profile file at {path}", file=sys.stderr)
        return None
    try:
        if path.stat().st_size > MAX_PROFILE_FILE_BYTES:
            print("Profile file is too large to be a profile file.", file=sys.stderr)
            return None
        return load_profiles(path.read_text(encoding="utf-8"))
    except ProfileError as exc:
        print(f"Profile file is invalid: {exc}", file=sys.stderr)
    except (OSError, UnicodeDecodeError):
        print("Profile file could not be read as UTF-8 text.", file=sys.stderr)
    return None


def _cmd_score(args: argparse.Namespace) -> int:
    layout = DataLayout(resolve_home())
    roster, code = _load_roster(layout, args.uid)
    if roster is None:
        return code
    snapshot = _current_snapshot(layout)
    if snapshot is None:
        print("No data snapshot: run `genshin-companion sync` first.", file=sys.stderr)
        return 1
    profiles = _read_profiles(Path(args.profiles))
    if profiles is None:
        return 1
    print(render_scores(score_roster(roster, snapshot, profiles)))
    return 0


def _cmd_profiles(args: argparse.Namespace) -> int:
    profiles = _read_profiles(Path(args.file))
    if profiles is None:
        return 1
    snapshot = _current_snapshot(DataLayout(resolve_home()))
    for p in profiles:
        print(render_profile(p))
    if snapshot is None:
        print("No data snapshot: run `genshin-companion sync` to validate profiles.")
        return 0
    problems = validate_profiles(profiles, snapshot)
    for problem in problems:
        print(f"  ! {problem}")
    print(f"{len(profiles)} profile(s), {len(problems)} problem(s).")
    return 1 if problems else 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    layout = DataLayout(resolve_home())
    store = SnapshotStore(layout)
    try:
        if args.action == "rollback":
            print(f"current snapshot is now {store.rollback()}")
            return 0
        snap = store.current()
        if snap is None:
            print("No snapshot yet. Run: genshin-companion sync")
            return 1
        if args.action == "changelog":
            history = store.history()
            index = history.index(store.current_id() or "")
            if index == 0:
                print("No earlier snapshot to compare with.")
                return 0
            print(render(diff(store.load(history[index - 1]), snap)))
            return 0
        print(f"snapshot:     {store.current_id()}")
        print(f"game version: {snap.game_version}")
        print(f"fetched at:   {snap.fetched_at.isoformat()}")
        print("confidence:   " + ", ".join(f"{k}={v}" for k, v in snap.confidence.items()))
        print(
            f"contents:     {len(snap.characters)} characters, {len(snap.weapons)} weapons, "
            f"{len(snap.artifact_sets)} artifact sets, {len(snap.substat_tiers)} substat tiers"
        )
        for src in snap.sources:
            kind = "pinned" if src.pinned else "UNPINNED"
            print(
                f"  source {src.source}: {src.url} [{kind} {src.ref[:12]}] sha256={src.sha256[:12]}"
            )
        for note in snap.notes:
            print(f"  note: {note}")
    except StoreError as exc:
        print(f"Snapshot store problem: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genshin-companion",
        description="Local-first, unofficial Genshin Impact companion (not HoYoverse-affiliated)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="show where data is stored").set_defaults(func=_cmd_paths)
    sub.add_parser("net-policy", help="show what the app may send over the network").set_defaults(
        func=_cmd_net_policy
    )
    sync = sub.add_parser("sync", help="download, validate and promote game data")
    sync.add_argument("--latest", action="store_true", help="fetch the unpinned latest Enka data")
    sync.add_argument(
        "--allow-single-source",
        action="store_true",
        help="accept data without the cross-check source (marked provisional)",
    )
    sync.add_argument(
        "--accept-held", action="store_true", help="promote a snapshot that was held for review"
    )
    sync.set_defaults(func=_cmd_sync)
    imp = sub.add_parser("import", help="import a roster by UID (sends the UID to Enka) or --file")
    imp.add_argument("uid", nargs="?", help="9-10 digit UID")
    imp.add_argument("--file", help="read a saved Enka response instead of contacting Enka")
    imp.set_defaults(func=_cmd_import)
    ros = sub.add_parser("roster", help="show the imported roster with verified roll breakdowns")
    ros.add_argument("uid", nargs="?")
    ros.set_defaults(func=_cmd_roster)
    sco = sub.add_parser("score", help="rate the imported roster's artifacts against the profiles")
    sco.add_argument("uid", nargs="?")
    sco.add_argument("--profiles", default="profiles/characters.toml")
    sco.set_defaults(func=_cmd_score)
    prof = sub.add_parser("profiles", help="list and validate the curated stat profiles")
    prof.add_argument("--file", default="profiles/characters.toml")
    prof.set_defaults(func=_cmd_profiles)
    snap = sub.add_parser("snapshot", help="inspect or roll back the current game-data snapshot")
    snap.add_argument("action", choices=["status", "changelog", "rollback"])
    snap.set_defaults(func=_cmd_snapshot)
    clear = sub.add_parser("clear-data", help="delete all of your local user data")
    clear.add_argument("--yes", action="store_true", help="confirm deletion")
    clear.add_argument(
        "--include-game-data", action="store_true", help="also delete downloaded game snapshots"
    )
    clear.set_defaults(func=_cmd_clear_data)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
