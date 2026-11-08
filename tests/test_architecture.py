"""Static guarantees from SPEC.md that must not rot: networking, determinism, dependency direction.

These scan the source with ``ast`` (nothing is imported or executed). They are TRIPWIRES against
accidental or careless violations, not a sandbox: a determined author with write access to this
repository can always defeat a static check. They were red-teamed once (2026-11-08); the cases found
then (relative imports, re-exports, star imports, encoding cookies, hidden file types, unguarded new
packages, transitive reach, attribute calls) are covered below.

Known follow-up: the Phase 4b local API server needs to *listen* on 127.0.0.1, which imports socket
machinery. Add a narrowly scoped exemption for that single module when it is written.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "genshin_companion"
PKG = "genshin_companion"
NET_CLIENT = SRC / "net" / "client.py"

# Anything that can open a socket or speak HTTP/other protocols.
NETWORK_MODULES = {
    "httpx", "httpcore", "requests", "urllib3", "aiohttp", "websockets", "websocket", "h11", "h2",
    "pycurl", "treq", "grpc", "socket", "ssl", "selectors", "ftplib", "smtplib", "poplib",
    "imaplib", "telnetlib", "xmlrpc", "socketserver", "http.client", "http.server",
    "urllib.request", "asyncio", "wsgiref", "webbrowser", "uvicorn", "fastapi",
}  # fmt: skip
# Executing / deserialising untrusted data, or reaching the interpreter internals.
DANGEROUS_MODULES = {
    "pickle", "cPickle", "marshal", "shelve", "dill", "cloudpickle", "importlib", "runpy", "code",
    "codeop", "ctypes", "builtins", "imp", "pkgutil", "zipimport",
}  # fmt: skip
DANGEROUS_BARE_CALLS = {"eval", "exec", "compile", "__import__"}
DANGEROUS_ATTR_CALLS = {"eval", "exec", "__import__"}  # `re.compile` etc. are fine
# Process spawning: never reachable, even transitively, from the model-facing layers.
PROCESS_STRICT = {"subprocess", "multiprocessing", "pty", "ctypes", "pexpect"}
# Direct imports forbidden in the model-facing layer itself (a read-only lookup layer).
CHAT_DIRECT_BANNED = PROCESS_STRICT | {"os", "shutil", "tempfile", "glob"}
LLM_CLIENT_MODULES = {
    "ollama", "openai", "anthropic", "langchain", "litellm", "transformers", "llama_cpp", "torch",
}  # fmt: skip
IO_MODULES = {
    "pathlib", "io", "sqlite3", "tempfile", "glob", "fileinput", "json", "csv", "gzip", "zipfile",
    "tarfile", "logging", "os", "shutil",
}  # fmt: skip

ALLOWED_DEPS: dict[str, set[str]] = {
    "scoring": {"data"},
    "data": {"net"},
    "net": set(),
    "enka": {"net", "data"},
    "builds": {"scoring", "data"},
    "lore": {"data", "net"},
    "teams": {"scoring", "builds", "data"},
    "chat": {"builds", "scoring", "lore", "data"},
    "app": {"chat", "builds", "scoring", "lore", "data", "enka", "teams", "net"},
}
# Shared leaf helpers living directly in the package, importable from anywhere.
LEAF_MODULES = {"__init__", "paths", "config"}
# Packages whose guards below would be vacuous if someone renamed them.
GUARDED = ("scoring", "chat", "net", "data")


# -- scanner -------------------------------------------------------------------------------------


def py_files(root: Path = SRC) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def parse(path: Path) -> ast.Module:
    # Parse BYTES so PEP 263 coding cookies are honoured exactly as the interpreter would.
    return ast.parse(path.read_bytes(), filename=str(path))


def absolute_import(path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def imported_modules(path: Path) -> set[str]:
    """Every dotted module name imported by the file, incl. parent prefixes and imported names."""
    found: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = absolute_import(path, node)
            names = [base, *(f"{base}.{a.name}" for a in node.names if a.name != "*")]
        else:
            continue
        for name in names:
            parts = name.split(".")
            found.update(".".join(parts[: i + 1]) for i in range(len(parts)))
    return found


def imported_leaves(path: Path) -> set[str]:
    """Final names pulled in by ``from X import name`` (catches ``from pkg.client import httpx``)."""
    out: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.ImportFrom):
            out.update(a.name for a in node.names)
    return out


def star_imports(path: Path) -> list[str]:
    return [
        absolute_import(path, n)
        for n in ast.walk(parse(path))
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
    ]


def bare_calls(path: Path) -> set[str]:
    return {
        n.func.id
        for n in ast.walk(parse(path))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def attr_calls(path: Path) -> set[str]:
    return {
        n.func.attr
        for n in ast.walk(parse(path))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


def all_names(path: Path) -> set[str]:
    return {n.id for n in ast.walk(parse(path)) if isinstance(n, ast.Name)}


def package_files(sub: str) -> list[Path]:
    return py_files(SRC / sub)


def hits(mods: set[str], banned: set[str]) -> set[str]:
    return {m for m in mods if any(m == b or m.startswith(b + ".") for b in banned)}


@cache
def _internal_modules() -> dict[str, Path]:
    return {module_name(p): p for p in py_files()}


@cache
def reach(path: Path) -> frozenset[str]:
    """External modules transitively imported (through the internal import graph) from ``path``."""
    internal = _internal_modules()
    seen: set[Path] = set()
    external: set[str] = set()
    todo = [path]
    while todo:
        current = todo.pop()
        for mod in imported_modules(current):
            if mod in internal:
                target = internal[mod]
                if target not in seen:
                    seen.add(target)
                    todo.append(target)
            elif not mod.startswith(PKG):
                external.add(mod)
    return frozenset(external)


# -- scanner self-tests: each red-team bypass must be caught ----------------------------------------


def write(tmp_path: Path, text: str | bytes, name: str = "x.py") -> Path:
    p = tmp_path / name
    p.write_bytes(text if isinstance(text, bytes) else text.encode())
    return p


def first_import_from(code: str) -> ast.ImportFrom:
    node = ast.parse(code).body[0]
    assert isinstance(node, ast.ImportFrom)
    return node


def test_scanner_detects_plain_and_dotted_imports(tmp_path: Path) -> None:
    p = write(tmp_path, "import httpx\nfrom urllib import request\nfrom http import client\n")
    assert {"httpx", "urllib.request", "http.client"} <= imported_modules(p)


def test_scanner_detects_encoding_cookie_smuggling(tmp_path: Path) -> None:
    p = write(tmp_path, b"# coding: utf-7\n# +AAo-import httpx\nX = 1\n")
    assert "httpx" in imported_modules(p)  # parsed as the interpreter would


def test_scanner_detects_reexports_and_star_imports(tmp_path: Path) -> None:
    p = write(tmp_path, "from genshin_companion.net.client import httpx\nfrom a.b import *\n")
    assert "httpx" in imported_leaves(p)
    assert star_imports(p) == ["a.b"]


def test_scanner_resolves_relative_imports() -> None:
    in_net_init = SRC / "net" / "__init__.py"
    assert absolute_import(in_net_init, first_import_from("from .client import X")) == (
        "genshin_companion.net.client"
    )
    in_chat_mod = SRC / "chat" / "tools.py"
    assert absolute_import(in_chat_mod, first_import_from("from ..net import X")) == (
        "genshin_companion.net"
    )
    assert absolute_import(in_chat_mod, first_import_from("from . import X")) == (
        "genshin_companion.chat"
    )


def test_scanner_detects_attribute_style_dynamic_code(tmp_path: Path) -> None:
    p = write(tmp_path, "import builtins\nbuiltins.eval('1')\nx.exec('2')\nre.compile('a')\n")
    assert {"eval", "exec"} <= attr_calls(p)
    assert "compile" in attr_calls(p) and "compile" not in DANGEROUS_ATTR_CALLS
    assert "builtins" in imported_modules(p)


def test_scanner_detects_dunder_builtins_name(tmp_path: Path) -> None:
    assert "__builtins__" in all_names(write(tmp_path, "__builtins__['eval']('1')\n"))


# -- file layout: nothing the scanner cannot see ------------------------------------------------------


def test_every_file_under_src_is_a_scanned_python_file() -> None:
    odd = []
    for p in SRC.rglob("*"):
        if p.is_dir():
            continue
        if "__pycache__" in p.parts:
            if p.suffix != ".pyc":  # a .py hidden in __pycache__ would still be importable
                odd.append(rel(p))
        elif p.suffix != ".py" and p.name != "py.typed":
            odd.append(rel(p))  # .pyw/.pyd/.so/.dll/.pth/.pyc/data files are not scanned
    assert not odd, f"unscanned files under src: {odd}"


def test_every_package_directory_is_known_and_guarded_packages_exist() -> None:
    top = {p.name for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert top <= set(ALLOWED_DEPS), f"new package(s) {sorted(top - set(ALLOWED_DEPS))} need rules"
    for guarded in GUARDED:
        assert (SRC / guarded / "__init__.py").exists(), f"guarded package {guarded} was renamed"
    modules = {p.stem for p in SRC.glob("*.py")}
    assert modules <= LEAF_MODULES, f"new top-level module(s) {sorted(modules - LEAF_MODULES)}"


# -- networking --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [p for p in py_files() if p != NET_CLIENT], ids=rel)
def test_only_net_client_may_do_networking(path: Path) -> None:
    bad = hits(imported_modules(path), NETWORK_MODULES)
    assert not bad, f"{rel(path)} imports network modules {sorted(bad)}; use net.SafeHttpClient"
    leaked = imported_leaves(path) & NETWORK_MODULES
    assert not leaked, f"{rel(path)} pulls network names {sorted(leaked)} out of another module"
    assert not star_imports(path), f"{rel(path)} uses a star import"


def test_net_client_does_not_use_forbidden_http_verbs() -> None:
    src = NET_CLIENT.read_text(encoding="utf-8")
    for verb in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"):
        assert f'"{verb}"' not in src, f"net/client.py mentions {verb}"
    public_methods = {
        n.name
        for cls in ast.walk(parse(NET_CLIENT))
        if isinstance(cls, ast.ClassDef) and cls.name == "SafeHttpClient"
        for n in cls.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    }
    assert public_methods == {"get", "head", "close"}


def test_net_client_never_enables_redirect_following_or_env_trust() -> None:
    src = NET_CLIENT.read_text(encoding="utf-8")
    assert "follow_redirects=False" in src
    assert "trust_env=False" in src
    assert "verify=False" not in src


def test_net_package_exports_do_not_include_http_libraries() -> None:
    init = SRC / "net" / "__init__.py"
    assert not (imported_leaves(init) & NETWORK_MODULES)


# -- untrusted data ------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", py_files(), ids=rel)
def test_no_unsafe_deserialisation_or_dynamic_code(path: Path) -> None:
    bad_imports = hits(imported_modules(path), DANGEROUS_MODULES)
    bad_calls = bare_calls(path) & DANGEROUS_BARE_CALLS
    bad_attrs = attr_calls(path) & DANGEROUS_ATTR_CALLS
    assert not bad_imports, f"{rel(path)} imports {sorted(bad_imports)}"
    assert not bad_calls, f"{rel(path)} calls {sorted(bad_calls)}"
    assert not bad_attrs, f"{rel(path)} calls .{sorted(bad_attrs)}"
    assert "__builtins__" not in all_names(path)


# -- scoring purity ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", package_files("scoring"), ids=rel)
def test_scoring_is_pure(path: Path) -> None:
    mods = imported_modules(path)
    banned = hits(mods, NETWORK_MODULES | PROCESS_STRICT | LLM_CLIENT_MODULES | IO_MODULES) | {
        m for m in mods if m.startswith(PKG + ".") and m.split(".")[1] not in {"scoring", "data"}
    }
    assert not banned, f"{rel(path)} must stay pure/deterministic but imports {sorted(banned)}"
    assert not ({"open", "print", "input"} & bare_calls(path))
    assert not hits(mods, {"random", "time", "datetime", "secrets", "uuid"}), (
        f"{rel(path)} imports a source of non-determinism"
    )
    # Nothing it can reach, even indirectly, may touch the network, a process, an LLM client or the
    # file system (``scoring`` may import ``data``, so ``data.store`` must stay out of its reach).
    transitive = hits(
        set(reach(path)), NETWORK_MODULES | PROCESS_STRICT | LLM_CLIENT_MODULES | IO_MODULES
    )
    assert not transitive, f"{rel(path)} transitively reaches {sorted(transitive)}"


# -- chat is a narrator with read-only tools -------------------------------------------------------------


@pytest.mark.parametrize("path", package_files("chat"), ids=rel)
def test_chat_has_no_shell_process_network_or_write_capability(path: Path) -> None:
    banned = hits(imported_modules(path), CHAT_DIRECT_BANNED | NETWORK_MODULES)
    assert not banned, f"{rel(path)} gives the model reach it must not have: {sorted(banned)}"
    transitive = hits(set(reach(path)), NETWORK_MODULES | PROCESS_STRICT)
    assert not transitive, (
        f"{rel(path)} transitively reaches {sorted(transitive)}; chat tools may only import "
        "read-only modules (e.g. data.models/store), never data.sync or net"
    )
    writers = {
        "system",
        "popen",
        "write_text",
        "write_bytes",
        "unlink",
        "rmtree",
        "remove",
        "rename",
    }
    assert not (writers & attr_calls(path))


# -- dependency direction: app -> chat -> (builds, scoring, lore, data) ----------------------------------


@pytest.mark.parametrize("sub", sorted(ALLOWED_DEPS))
def test_dependency_direction(sub: str) -> None:
    for path in package_files(sub):
        for mod in imported_modules(path):
            parts = mod.split(".")
            if parts[0] != PKG or len(parts) < 2:
                continue
            target = parts[1]
            if target == sub or target.startswith("_") or target in LEAF_MODULES:
                continue
            assert target in ALLOWED_DEPS[sub], (
                f"{rel(path)}: {sub} must not import {target}; ok: {sorted(ALLOWED_DEPS[sub])}"
            )
