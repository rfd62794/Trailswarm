"""Named segment suites (runs/segment_sets.json): the roster of segment variety for tests, runs and analysis.

A suite resolves to a list of Members ``{"key", "starter"}`` (starter None unless the suite pins one).
Rules: first n of the chain, every segment (chain), the n worst-health, one per end-map type
(per_map_type), listed segments x listed starters (per_starter), or an explicit list. A missing or
malformed file yields the built-in defaults; a malformed suite is skipped on its own (like seg_hold).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

FILE = Path("runs") / "segment_sets.json"

DEFAULT_SUITES = {
    "smoke":    {"rule": "first", "n": 5},
    "campaign": {"rule": "chain"},
    "stress":   {"rule": "worst_health", "n": 5},
    "variety":  {"rule": "per_map_type"},
    "starters": {"rule": "per_starter", "segments": ["to_viridian", "beat_brock"],
                "starters": ["bulbasaur", "charmander", "squirtle"]},
    "mine":     {"rule": "list", "segments": ["to_route3", "beat_misty"]},
}

RULES = ("first", "chain", "worst_health", "per_map_type", "per_starter", "list")


def _valid(spec) -> bool:
    return isinstance(spec, dict) and spec.get("rule") in RULES


def load_suites(root: Path) -> dict:
    """name -> suite spec: the file's valid suites over the built-in defaults; defaults alone when the
    file is missing or malformed."""
    out = dict(DEFAULT_SUITES)
    try:
        doc = json.loads((Path(root) / FILE).read_text(encoding="utf-8"))
        raw = doc["suites"]
    except (OSError, ValueError, KeyError, TypeError):
        return out
    if isinstance(raw, dict):
        for name, spec in raw.items():
            if isinstance(name, str) and _valid(spec):
                out[name] = spec   # a malformed suite is skipped on its own
    return out


def map_type(map_id: int | None, names: dict | None = None) -> str:
    """The TYPE of an end map from its atlas name: route | town | indoor | cave | other."""
    if map_id is None:
        return "other"
    if names is None:
        names = _names()
    n = str(names.get(str(map_id), ""))
    if n.startswith("ROUTE_"):
        return "route"
    if n.endswith("_CITY") or n.endswith("_TOWN"):
        return "town"
    if n.endswith(("_GYM", "_HOUSE", "_MART", "_POKECENTER")) or n.startswith("SS_ANNE_"):
        return "indoor"
    if n.startswith("MT_") or n.endswith(("_CAVE", "_TUNNEL")) or "DIGLETTS_CAVE" in n:
        return "cave"
    return "other"


def _names() -> dict:
    try:
        return _names._cache
    except AttributeError:
        try:
            from pokeagent import atlas
            _names._cache = json.loads((Path(atlas.__file__).parent / "map_names.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _names._cache = {}
        return _names._cache


def _end_map(seg, st: dict) -> int | None:
    """The map a segment ends on: its map stop, else the last map of its newest attempt with maps."""
    if seg.stop_map is not None:
        return seg.stop_map
    for a in reversed(st["attempts"]):
        if a.get("maps"):
            return a["maps"][-1]
    return None


def _member(key, starter=None) -> dict:
    return {"key": key, "starter": starter}


def resolve(name: str, doc: dict, grades, root, log=print) -> list[dict] | None:
    """The Members of suite ``name`` (None when unknown/malformed). ``grades`` = grade_all's list for
    the health column; ``root`` reads the hold file (held members are dropped where the rule says)."""
    import seg_hold
    import seg_store as ss
    spec = load_suites(root).get(name)
    if spec is None:
        return None
    segs = ss.layout(doc)
    by_key = {s.key: s for s in segs}
    if spec["rule"] == "chain":
        return [_member(s.key) for s in segs]
    if spec["rule"] == "first":
        return [_member(s.key) for s in segs[:int(spec.get("n") or 5)]]
    if spec["rule"] == "list":
        out = []
        for k in spec.get("segments") or []:
            if k in by_key:
                out.append(_member(k))
            else:
                log(f"suite {name}: unknown segment {k!r} dropped")
        return out
    if spec["rule"] == "per_starter":
        return [_member(k, st) for k in spec.get("segments") or [] if k in by_key
                for st in spec.get("starters") or []]
    if spec["rule"] == "worst_health":
        from datetime import datetime
        now = datetime.fromtimestamp(time.time()).astimezone()
        held = [h for h in seg_hold.read_file(seg_hold.path(root)) if h.until > now]
        gmap = {g.key: g for g in grades or []}
        ranked = sorted((s for s in segs if not any(h.covers(s.key) for h in held)),
                        key=lambda s: ((gmap.get(s.key) is None or gmap[s.key].health is None),
                                       gmap[s.key].health if gmap.get(s.key) and gmap[s.key].health is not None else 0.0))
        return [_member(s.key) for s in ranked[:int(spec.get("n") or 5)]]
    if spec["rule"] == "per_map_type":
        names, seen, out = _names(), set(), []
        for s in segs:
            t = map_type(_end_map(s, ss.stat(doc, s.key)), names)
            if t not in seen:
                seen.add(t)
                out.append(_member(s.key))
        return out
    return None
