"""Shared synthetic fixtures (shape-faithful, made-up numbers). Upstream files are unlicensed, so no
real data is committed."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from genshin_companion.data.models import Snapshot
from genshin_companion.data.normalize import build_snapshot, parse_amber, parse_enka

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def enka_files(**over: Any) -> dict[str, bytes]:
    files: dict[str, Any] = {
        "affixes": {
            # rarity digit + "01" + 2-digit PropType + position
            "501021": {"PropType": 2, "Efficiency": 0.7, "Position": 1, "Value": 200.0},
            "501022": {"PropType": 2, "Efficiency": 1.0, "Position": 2, "Value": 300.0},
            "501061": {"PropType": 6, "Efficiency": 0.7, "Position": 1, "Value": 0.04},
            "501062": {"PropType": 6, "Efficiency": 1.0, "Position": 2, "Value": 0.06},
            "941001": {"PropType": 3, "Efficiency": 1.0, "Position": 1, "Value": 0.09},
        },
        "affixes_legacy": {
            "501021": {"propType": "FIGHT_PROP_HP", "efficiency": 0.7, "position": 1},
            "501022": {"propType": "FIGHT_PROP_HP", "efficiency": 1, "position": 2},
            "501061": {"propType": "FIGHT_PROP_ATTACK_PERCENT", "efficiency": 0.7, "position": 1},
            "501062": {"propType": "FIGHT_PROP_ATTACK_PERCENT", "efficiency": 1, "position": 2},
        },
        "relic_levels": {"5": {"1": {"2": 700.0, "6": 0.07}, "2": {"2": 900.0, "6": 0.09}}},
        "avatars": {
            "10000002": {
                "Element": "Ice",
                "NameTextMapHash": 111,
                "QualityType": "QUALITY_ORANGE",
                "WeaponType": "WEAPON_SWORD_ONE_HAND",
                "BaseProps": {"1": 1000.0, "4": 26.0},
                "Costumes": {},
                "Extra": "ignored",
            },
            "10000099": {},  # upstream placeholder entry
        },
        "weapons": {
            "11501": {
                "Rarity": 5,
                "WeaponType": 1,
                "NameTextMapHash": 222,
                "BaseProps": {"4": 46.0},
                "RefineProps": {},
            }
        },
        "relics": {
            "Items": {"20412": {"Rarity": 4, "EquipType": 3, "Icon": "/ui/x.png", "SetId": 15025}},
            "Sets": {"15025": {"Name": "333", "AddProps": {"6": 0.18}}},
        },
        "locs": {"en": {"111": "Test Hero", "222": "Test Sword", "333": "Test Set"}, "de": {}},
    }
    files.update(over)
    return {k: json.dumps(v).encode() for k, v in files.items()}


def amber_files(**over: Any) -> dict[str, bytes]:
    files: dict[str, Any] = {
        "reliquaryCurve": {
            "response": 200,
            "data": {
                "initial": {},
                "ranked": {
                    "5": {
                        "1": {"FIGHT_PROP_HP": 700, "FIGHT_PROP_ATTACK_PERCENT": 0.07},
                        "2": {"FIGHT_PROP_HP": 900, "FIGHT_PROP_ATTACK_PERCENT": 0.09},
                    }
                },
                "affix": {
                    "5": {
                        "FIGHT_PROP_HP": [200, 300],
                        "FIGHT_PROP_ATTACK_PERCENT": [0.04, 0.06],
                    }
                },
            },
        },
        "changelog": {
            "response": 200,
            "data": {
                "71": {"items": {}, "version": "7.1"},
                "72": {"items": {}, "version": "7.2"},
            },
        },
    }
    files.update(over)
    return {k: json.dumps(v).encode() for k, v in files.items()}


def snapshot(
    enka: dict[str, bytes] | None = None, amber: dict[str, bytes] | None = None
) -> Snapshot:
    e = parse_enka(enka or enka_files())
    a = parse_amber(amber or amber_files()) if amber != {} else None
    return build_snapshot(e, a, sources=[], fetched_at=NOW)


class StreamingTransport(httpx.BaseTransport):
    """Wrap a request handler so responses behave like real network streams.

    ``httpx.Response(content=...)`` is already read, which a real transport never returns; the
    client iterates raw wire bytes, so mocks must hand back an unread byte stream.
    """

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._handler(request)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=httpx.ByteStream(response.read()),
            extensions=response.extensions,
        )


def scoring_snapshot(substat_confidence: str = "curated") -> Snapshot:
    """A tiny hand-made tier table with round numbers, for hand-checkable scoring tests.

    Not game data. 5-star tiers: CRIT 0.02/0.03/0.04, CRIT DMG 0.04/0.06/0.08, ATK% 0.04/0.05/0.06,
    HP 100/200/300, EM 10/20. 4-star ATK%: 0.03/0.04/0.05.
    """
    from genshin_companion.data.models import SubstatTier

    p = "FIGHT_PROP_"
    table = {
        ("500101", 5, p + "CRITICAL", 1, 0.02), ("500102", 5, p + "CRITICAL", 2, 0.03), ("500103", 5, p + "CRITICAL", 3, 0.04),
        ("500201", 5, p + "CRITICAL_HURT", 1, 0.04), ("500202", 5, p + "CRITICAL_HURT", 2, 0.06), ("500203", 5, p + "CRITICAL_HURT", 3, 0.08),
        ("500301", 5, p + "ATTACK_PERCENT", 1, 0.04), ("500302", 5, p + "ATTACK_PERCENT", 2, 0.05), ("500303", 5, p + "ATTACK_PERCENT", 3, 0.06),
        ("400301", 4, p + "ATTACK_PERCENT", 1, 0.03), ("400302", 4, p + "ATTACK_PERCENT", 2, 0.04), ("400303", 4, p + "ATTACK_PERCENT", 3, 0.05),
        ("500401", 5, p + "HP", 1, 100.0), ("500402", 5, p + "HP", 2, 200.0), ("500403", 5, p + "HP", 3, 300.0),
        ("500501", 5, p + "ELEMENT_MASTERY", 1, 10.0), ("500502", 5, p + "ELEMENT_MASTERY", 2, 20.0),
    }  # fmt: skip
    return Snapshot(
        game_version="7.2",
        fetched_at=NOW,
        sources=[],
        confidence={
            "substat_tiers": substat_confidence,  # type: ignore[dict-item]
            "main_stats": "curated",
            "characters": "curated",
            "weapons": "curated",
            "artifact_sets": "curated",
        },
        notes=[],
        prop_names={},
        substat_tiers=[
            SubstatTier(affix_id=a, rarity=r, stat=s, position=pos, value=v)
            for a, r, s, pos, v in sorted(table)
        ],
        main_stats=[],
        characters=[],
        weapons=[],
        artifact_sets=[],
        artifacts=[],
    )
