"""Serialization helpers for grind/points.py (split out: points.py sits at the 300-line ceiling).

``points_of`` tolerates malformed rows: a bad entry in the shared table must not fail the whole load,
but each skip is logged once per process now (the silent-skip hard rule from the PR #165 review).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
_warned: set = set()


def _warn_once(key: str, msg: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        log.info(msg, *args)


def patch_of(maps: dict, map_id: int) -> list:  # [[x, y]] grass tiles: encounters keys with count >= 1
    enc = (maps.get(str(map_id)) or {}).get("encounters") or {}
    return sorted(([int(x) for x in k.split(",")] for k, n in enc.items() if n >= 1), key=lambda t: (t[1], t[0]))


def species_of(kb: dict | None, map_id: int) -> list:  # [[species, min, max]] from the ROM wild table
    row = ((kb or {}).get("wild_by_map") or {}).get(str(map_id)) or (kb or {}).get("wild_by_map", {}).get(map_id) or {}
    res: dict = {}
    for lv, spname in row.get("grass") or []:
        cur = res.setdefault(spname, [spname, lv, lv])
        cur[1], cur[2] = min(cur[1], lv), max(cur[2], lv)
    return sorted(res.values())


def band_of(species: list) -> tuple:  # default band: top wild level -2..+6 (DEFAULT_BAND when unknown)
    from pokeagent.grind.points import BAND_HI, BAND_LO, DEFAULT_BAND
    hi = max((t[2] for t in species), default=None)
    return (hi + BAND_LO, hi + BAND_HI) if hi is not None else DEFAULT_BAND


def points_of(rows: dict) -> dict:  # {map id: GrindPoint} from a serialized table; malformed skipped (logged once)
    from pokeagent.grind.points import GrindPoint
    pts = {}
    for k, v in (rows or {}).items():
        try:
            pts[int(k)] = GrindPoint.from_dict(v)
        except (KeyError, TypeError, ValueError) as e:
            _warn_once("points_of", "grind points: skipping malformed row %r (%r)", k, e)
    return pts
