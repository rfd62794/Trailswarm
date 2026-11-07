"""diff: what changed between two maps.json snapshots - 'what did this run learn'."""
from __future__ import annotations

import json

from pokeagent.brain.common import mid_key

MAX_LIST = 100


def _freeze(v):
    try:
        hash(v)
        return v
    except TypeError:
        return json.dumps(v, sort_keys=True)


def _cap(items: list) -> dict:
    return {"count": len(items), "items": items[:MAX_LIST], "truncated": len(items) > MAX_LIST}


def _value_diff(va, vb) -> dict:
    """One level of added/removed/changed for dicts and lists; {'a','b'} for scalars."""
    if isinstance(va, dict) and isinstance(vb, dict):
        ka, kb = set(va), set(vb)
        changed = sorted(str(k) for k in ka & kb if va[k] != vb[k])
        return {"added": _cap(sorted(str(k) for k in kb - ka)),
                "removed": _cap(sorted(str(k) for k in ka - kb)),
                "changed": _cap(changed)}
    if isinstance(va, list) and isinstance(vb, list):
        fa = {_freeze(v) for v in va}
        fb = {_freeze(v) for v in vb}
        added = [v for v in vb if _freeze(v) not in fa]
        removed = [v for v in va if _freeze(v) not in fb]
        return {"added": _cap(added), "removed": _cap(removed)}
    return {"a": va, "b": vb}


def diff(a: dict, b: dict) -> dict:
    """Structural diff of two maps.json payloads: per-map field diffs plus global tables."""
    a, b = a or {}, b or {}
    am, bm = a.get("maps") or {}, b.get("maps") or {}
    maps_out = {}
    for mid in sorted(set(am) | set(bm), key=mid_key):
        da, db = am.get(mid), bm.get(mid)
        if da is None:
            maps_out[mid] = {"added": True}
            continue
        if db is None:
            maps_out[mid] = {"removed": True}
            continue
        fields = {}
        for key in sorted(set(da) | set(db), key=str):
            va, vb = da.get(key), db.get(key)
            if va != vb:
                fields[key] = _value_diff(va, vb)
        if fields:
            maps_out[mid] = {"fields": fields}
    globals_out = {}
    for key in sorted(set(a) | set(b)):
        if key in ("maps", "updated"):
            continue
        va, vb = a.get(key), b.get(key)
        if va != vb:
            globals_out[key] = _value_diff(va, vb)
    out = {"maps": maps_out, "globals": globals_out}
    if a.get("updated") != b.get("updated"):
        out["meta"] = {"updated": {"a": a.get("updated"), "b": b.get("updated")}}
    return out
