"""Fold RAM observations and ram_map.json entries into a per-game measured address table. Pure: no file I/O.

Each sample credits only the tightest entry covering its address (smallest size, then name, as
``ram_lookup.query`` orders them). The output holds counts and contexts, never a raw observed value,
and none of the map's ``source``/``sym``/``evidence``/``note``/``alias`` text.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from pokeagent.ram_lookup import MapEntry
from pokeagent.ramlab.observations import GAMES, Sample

SCHEMA_VERSION = 1
SOURCE_MAP = "src/pokeagent/data/ram_map.json"
MAX_CONTEXTS = 8

STATUS_RULES = {
    "not-exercised": "no samples for this game credited to the entry",
    "believed": "at least one sample, but fewer than 2 distinct values or fewer than 2 distinct contexts",
    "measured": "at least 2 distinct values AND at least 2 distinct contexts",
}


def tightest(entries: Iterable[MapEntry], addr: int) -> MapEntry | None:
    covering = [e for e in entries if e.covers(addr)]
    return min(covering, key=lambda e: (e.size, e.name)) if covering else None


def status_for(samples: list[Sample]) -> str:
    if not samples:
        return "not-exercised"
    values = {s.value for s in samples}
    contexts = {s.context for s in samples}
    return "measured" if len(values) >= 2 and len(contexts) >= 2 else "believed"


def game_record(samples: list[Sample]) -> dict:
    return {
        "status": status_for(samples),
        "samples": len(samples),
        "distinct_values": len({s.value for s in samples}),
        "exercised_by": sorted({s.context for s in samples})[:MAX_CONTEXTS],
    }


def _key(e: MapEntry) -> tuple[int, str]:
    return (e.addr, e.name)


def build_table(entries: Iterable[MapEntry], samples_by_game: Mapping[str, Iterable[Sample]]) -> dict:
    ordered = sorted(entries, key=lambda e: (e.addr, e.name, e.size))
    unknown = sorted(set(samples_by_game) - set(GAMES))
    if unknown:
        raise ValueError(f"unknown game key(s) {unknown}; allowed {list(GAMES)}")
    credited: dict[tuple[int, str], dict[str, list[Sample]]] = {_key(e): {g: [] for g in GAMES} for e in ordered}
    unmapped: dict[int, dict[str, int]] = {}
    hit_cache: dict[int, MapEntry | None] = {}
    for game in GAMES:
        for s in samples_by_game.get(game, ()):
            if s.addr not in hit_cache:
                hit_cache[s.addr] = tightest(ordered, s.addr)
            hit = hit_cache[s.addr]
            if hit is None:
                unmapped.setdefault(s.addr, {g: 0 for g in GAMES})[game] += 1
            else:
                credited[_key(hit)][game].append(s)
    rows = [{
        "addr": f"0x{e.addr:04X}",
        "label": e.name,
        "width": e.size,
        "type": e.encoding,
        "region": e.region,
        "ram_map_verified": e.verified,
        "games": {g: game_record(credited[_key(e)][g]) for g in GAMES},
    } for e in ordered]
    return {
        "schema_version": SCHEMA_VERSION,
        "games": list(GAMES),
        "source_map": SOURCE_MAP,
        "status_rules": dict(STATUS_RULES),
        "entries": rows,
        "unmapped": [{"addr": f"0x{a:04X}", "samples": counts} for a, counts in sorted(unmapped.items())],
    }


def status_counts(table: dict, game: str) -> dict[str, int]:
    counts = {s: 0 for s in STATUS_RULES}
    for row in table["entries"]:
        counts[row["games"][game]["status"]] += 1
    return counts
