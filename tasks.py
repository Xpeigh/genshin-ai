"""Cross-platform task runner (Windows has no `make`).

    uv run python tasks.py check            # lint + format check + types + tests + audit
    uv run python tasks.py check --skip-audit
    uv run python tasks.py fix              # auto-fix lint and formatting
    uv run python tasks.py lock             # refresh uv.lock (hashes are recorded there)
    uv run python tasks.py audit            # dependency vulnerability audit only

The audit step talks to PyPI/OSV. That is *development tooling*, not the shipped app, which only
ever uses genshin_companion.net. A failing/unreachable audit FAILS the check unless you pass
--skip-audit explicitly, so it cannot be skipped silently.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*cmd: str, env: dict[str, str] | None = None) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT, env=env)


def py(*args: str, env: dict[str, str] | None = None) -> int:
    return run(sys.executable, "-m", *args, env=env)


def real_snapshot_env() -> dict[str, str] | None:
    """Environment for the tests that need the REAL data snapshot (golden tests, never committed).

    Uses the repo-local ``data-home`` snapshot if one has been synced; otherwise those tests skip.
    """
    pointer = ROOT / "data-home" / "snapshots" / "current.json"
    try:
        current = json.loads(pointer.read_text(encoding="utf-8"))["current"]
    except (OSError, ValueError, KeyError):
        print("note: no data-home snapshot, golden tests will be skipped", flush=True)
        return None
    snapshot = ROOT / "data-home" / "snapshots" / current / "snapshot.json"
    if not snapshot.is_file():
        return None
    return {**os.environ, "GENSHIN_REAL_SNAPSHOT": str(snapshot)}


def audit() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        rc = py(
            "uv", "export", "--quiet", "--frozen", "--no-emit-project", "--no-dev", "--format",
            "requirements.txt", "--output-file", str(req),
        )  # fmt: skip
        if rc != 0:
            return rc
        # Hashes in the export are verified by pip-audit's resolver-free mode.
        return py(
            "pip_audit",
            "-r",
            str(req),
            "--no-deps",
            "--disable-pip",
            "--strict",
            "--require-hashes",
        )


def check(skip_audit: bool) -> int:
    steps: list[tuple[str, Callable[[], int]]] = [
        ("ruff lint", lambda: py("ruff", "check", ".")),
        ("ruff format", lambda: py("ruff", "format", "--check", ".")),
        ("mypy", lambda: py("mypy")),
        ("pytest", lambda: py("pytest", "-q", env=real_snapshot_env())),
    ]
    if not skip_audit:
        steps.append(("dependency audit", audit))
    failed = [name for name, fn in steps if fn() != 0]
    print("\n" + ("FAILED: " + ", ".join(failed) if failed else "ALL CHECKS PASSED"))
    if skip_audit:
        print("WARNING: dependency audit was skipped.")
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    if cmd == "check":
        return check(skip_audit="--skip-audit" in argv)
    if cmd == "fix":
        return py("ruff", "check", "--fix", ".") or py("ruff", "format", ".")
    if cmd == "lock":
        return py("uv", "lock")
    if cmd == "audit":
        return audit()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
