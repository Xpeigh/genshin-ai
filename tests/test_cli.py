from __future__ import annotations

from pathlib import Path

import pytest

from genshin_companion.app.cli import main
from genshin_companion.paths import MARKER_NAME, ensure_layout


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    monkeypatch.setenv("GENSHIN_COMPANION_HOME", str(h))
    return h


def test_paths_command_prints_layout_and_creates_nothing(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["paths"]) == 0
    out = capsys.readouterr().out
    assert str(home) in out
    assert not home.exists()  # read-only command


def test_net_policy_lists_allowlist_and_states_get_only(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["net-policy"]) == 0
    out = capsys.readouterr().out
    assert "GET" in out and "HTTPS" in out


def test_clear_data_requires_confirmation(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    layout = ensure_layout(home)
    (layout.user / "roster.json").write_text("x")
    assert main(["clear-data"]) == 2  # no --yes: nothing is deleted
    assert (layout.user / "roster.json").exists()
    assert "--yes" in capsys.readouterr().err


def test_clear_data_yes_deletes_user_data_only(home: Path) -> None:
    layout = ensure_layout(home)
    (layout.user / "roster.json").write_text("x")
    (layout.snapshots / "s.json").write_text("y")
    assert main(["clear-data", "--yes"]) == 0
    assert not (layout.user / "roster.json").exists()
    assert (layout.snapshots / "s.json").exists()
    assert (home / MARKER_NAME).exists()


def test_clear_data_on_missing_home_is_a_noop(home: Path) -> None:
    assert main(["clear-data", "--yes"]) == 0
    assert not home.exists()


def test_clear_data_refuses_foreign_directory(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home.mkdir()
    (home / "thesis.docx").write_text("precious")
    assert main(["clear-data", "--yes"]) == 1
    assert (home / "thesis.docx").exists()


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code != 0


# -- sync / snapshot ------------------------------------------------------------------------------


def test_sync_snapshot_status_and_rollback_end_to_end(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

    from genshin_companion.app import cli
    from genshin_companion.config import default_network_policy
    from genshin_companion.net import SafeHttpClient
    from helpers import StreamingTransport
    from test_data_sync import Server

    server = Server()
    client = SafeHttpClient(default_network_policy(), transport=StreamingTransport(server.handler))
    monkeypatch.setattr(cli, "_client_override", client)
    assert main(["sync"]) == 0
    assert "promoted" in capsys.readouterr().out
    assert main(["snapshot", "status"]) == 0
    out = capsys.readouterr().out
    assert "game version: 7.2" in out and "curated" in out and "pinned" in out
    assert main(["snapshot", "rollback"]) == 1  # only one snapshot: nothing earlier
    assert "no earlier" in capsys.readouterr().err
    assert main(["snapshot", "changelog"]) == 0


def test_snapshot_status_without_sync_explains_what_to_do(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["snapshot", "status"]) == 1
    assert "sync" in capsys.readouterr().out


# -- import / roster -------------------------------------------------------------------------------


def test_import_from_file_never_touches_the_network(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_enka_mapping import showcase

    saved = tmp_path / "my-showcase.json"
    saved.write_bytes(showcase())
    assert main(["import", "--file", str(saved)]) == 0
    out = capsys.readouterr().out
    assert "nothing was sent over the network" in out and "800123456" in out
    assert (home / "user" / "rosters" / "800123456.json").exists()
    assert main(["roster"]) == 0


def test_import_by_uid_warns_that_the_uid_is_sent(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from genshin_companion.app import cli
    from genshin_companion.config import default_network_policy
    from genshin_companion.net import SafeHttpClient
    from helpers import StreamingTransport
    from test_enka_client import Enka

    server = Enka()
    client = SafeHttpClient(default_network_policy(), transport=StreamingTransport(server.handler))
    monkeypatch.setattr(cli, "_client_override", client)
    assert main(["import", "800123456"]) == 0
    captured = capsys.readouterr()
    assert "sends this UID to enka.network" in captured.err
    assert len(server.requests) == 1
    assert main(["import", "800123456"]) == 0  # second call is served from the cache
    assert len(server.requests) == 1


def test_import_needs_a_uid_or_a_file(home: Path) -> None:
    assert main(["import"]) == 2


def test_import_rejects_a_bad_uid_without_a_request(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["import", "12"]) == 1
    assert "UID" in capsys.readouterr().err


def test_clear_data_removes_imported_rosters_and_the_enka_cache(home: Path, tmp_path: Path) -> None:
    from test_enka_mapping import showcase

    saved = tmp_path / "s.json"
    saved.write_bytes(showcase())
    main(["import", "--file", str(saved)])
    assert (home / "user" / "rosters" / "800123456.json").exists()
    assert main(["clear-data", "--yes"]) == 0
    assert not any((home / "user").iterdir())


# --- refresh, lookup and the no-login disclaimer ----------------------------------------------


def _fake_enka(monkeypatch: pytest.MonkeyPatch, **kwargs):  # type: ignore[no-untyped-def]
    from genshin_companion.app import cli
    from genshin_companion.config import default_network_policy
    from genshin_companion.net import SafeHttpClient
    from helpers import StreamingTransport
    from test_enka_client import Enka

    server = Enka(**kwargs)
    client = SafeHttpClient(default_network_policy(), transport=StreamingTransport(server.handler))
    monkeypatch.setattr(cli, "_client_override", client)
    return server


def test_import_states_that_no_hoyoverse_login_is_ever_used(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_enka(monkeypatch)
    assert main(["import", "800123456"]) == 0
    err = capsys.readouterr().err
    assert "never asks for your HoYoverse" in err and "Character Showcase" in err


def test_refresh_needs_a_saved_roster(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["import", "--refresh"]) == 1
    assert "import <uid>" in capsys.readouterr().err


def test_refresh_reuses_the_cache_until_enkas_window_has_passed(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = _fake_enka(monkeypatch)
    assert main(["import", "800123456"]) == 0
    capsys.readouterr()
    assert main(["import", "--refresh"]) == 0
    out = capsys.readouterr().out
    assert "800123456" in out and "cache" in out
    assert len(server.requests) == 1  # nothing new was requested inside the ttl


def test_refresh_fetches_again_when_the_window_is_over(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_enka_mapping import showcase

    server = _fake_enka(monkeypatch, body=showcase(ttl=0))  # a response that is stale at once
    assert main(["import", "800123456"]) == 0
    assert main(["import", "--refresh"]) == 0
    assert len(server.requests) == 2
    assert "refreshed" in capsys.readouterr().out


def test_refresh_stops_politely_when_rate_limited(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_enka_mapping import showcase

    _fake_enka(monkeypatch, body=showcase(ttl=0))
    assert main(["import", "800123456"]) == 0
    server = _fake_enka(monkeypatch, status=429, headers={"Retry-After": "30"})
    capsys.readouterr()
    assert main(["import", "--refresh"]) == 1
    assert "Rate limited" in capsys.readouterr().err and len(server.requests) == 1


def test_refresh_cannot_be_combined_with_a_uid_or_a_file(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["import", "--refresh", "800123456"]) == 2
    assert main(["import", "--refresh", "--file", "x.json"]) == 2
    assert "either" in capsys.readouterr().err


def test_lookup_previews_a_player_without_saving_anything(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = _fake_enka(monkeypatch)
    assert main(["lookup", "800123456"]) == 0
    captured = capsys.readouterr()
    assert "Tester" in captured.out and "57" in captured.out  # nickname and level
    assert "2 character(s)" in captured.out  # the showcase lists two, whatever is detailed
    assert "never asks for your HoYoverse" in captured.err and "sends this UID" in captured.err
    assert not (home / "user" / "rosters").exists() or not list(
        (home / "user" / "rosters").glob("*.json")
    )
    assert main(["import", "800123456"]) == 0  # the lookup's response is reused: still one request
    assert len(server.requests) == 1


def test_lookup_reports_a_closed_showcase_and_a_bad_uid(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from test_enka_mapping import showcase

    closed = json.loads(showcase())
    closed.pop("avatarInfoList")
    closed["playerInfo"].pop("showAvatarInfoList")
    server = _fake_enka(monkeypatch, body=json.dumps(closed).encode())
    assert main(["lookup", "800123456"]) == 0
    out = capsys.readouterr().out.lower()
    assert "closed" in out and "no characters" in out
    assert main(["lookup", "123"]) == 1  # a malformed UID never reaches the network
    assert len(server.requests) == 1
