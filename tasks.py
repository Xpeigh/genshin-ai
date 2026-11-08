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

import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*cmd: str) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def py(*args: str) -> int:
    return run(sys.executable, "-m", *args)


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
        ("pytest", lambda: py("pytest", "-q")),
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
