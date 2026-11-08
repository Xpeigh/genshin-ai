"""Static configuration. The network allowlist lives HERE, in code, on purpose.

Downloaded data and user-writable files must never be able to widen it. Adding a host is a
reviewed code change plus an entry in docs/data-sources.md explaining why and what is sent.
"""

from __future__ import annotations

from genshin_companion.net import NetworkPolicy

# Every entry needs a justification in docs/data-sources.md.
#   raw.githubusercontent.com  pinned Enka store files (game data, GET of a file path only)
#   gi.yatta.moe               Project Amber static curves + changelog (cross-check source)
#   enka.network              UID roster import. NOTE: the UID is part of the request URL.
DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {"raw.githubusercontent.com", "gi.yatta.moe", "enka.network"}
)


def default_network_policy() -> NetworkPolicy:
    return NetworkPolicy(allowed_hosts=DEFAULT_ALLOWED_HOSTS)
