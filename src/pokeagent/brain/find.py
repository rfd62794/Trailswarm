"""find: query the map memory - by legend kind, interaction text, item name, or warp destination."""
from __future__ import annotations

import json

from pokeagent.brain.common import known_tiles, mid_key, npc_tiles, parse_tile
from pokeagent.explorer import tilekind

MAX_RESULTS = 500


def _item_hits(data: dict, needle: str) -> list:
    """Global item records (runs/maps.json 'items') whose name or context mentions ``needle``."""
    out = []
    for rec in data.get("items") or []:
        if not isinstance(rec, dict):
            continue
        hay = f"{rec.get('item', '')} {rec.get('text', '')}".lower()
        if needle in hay:
            out.append({"kind": "item", "item": rec.get("item"), "id": rec.get("id"),
                        "map": rec.get("map"), "at": rec.get("at"), "delta": rec.get("delta"),
                        "text": (rec.get("text") or "")[:80]})
    return out


def find(data: dict, query: dict | None = None, **kw) -> dict:
    """Search map memory. Query keys (all optional, ANDed):

    ``map`` (int), ``kind`` (legend kind), ``text`` (substring of interaction text/choices),
    ``item`` (substring of item records), ``warps_to`` (destination map id).
    """
    q = dict(query or {})
    q.update(kw)
    q = {k: v for k, v in q.items() if v is not None}
    maps = data.get("maps") or {}
    only = q.get("map")
    mids = [str(only)] if only is not None else sorted(maps, key=mid_key)
    kind, text, warps_to = q.get("kind"), q.get("text"), q.get("warps_to")
    tile_types = data.get("tile_types") or {}
    grass_ids = data.get("grass_ids") or {}
    results = []
    truncated = False
    for mid in mids:
        d = maps.get(mid)
        if d is None:
            continue
        if warps_to is not None:
            for k, v in (d.get("warps") or {}).items():
                if isinstance(v, (list, tuple)) and len(v) == 3:
                    try:
                        if int(v[0]) == int(warps_to):
                            p = parse_tile(k)
                            results.append({"map": mid, "x": p[0] if p else None, "y": p[1] if p else None,
                                            "dir": str(k).split(",")[-1], "to": list(v), "kind": "warp"})
                    except (TypeError, ValueError):
                        continue
        if text is not None:
            needle = str(text).lower()
            for k, e in (d.get("interactions") or {}).items():
                hay = (((e or {}).get("text") or "") + " " + " ".join((e or {}).get("choices") or [])).lower()
                if needle in hay:
                    p = parse_tile(k)
                    results.append({"map": mid, "x": p[0] if p else None, "y": p[1] if p else None,
                                    "facing": str(k).split(",")[-1],
                                    "text": ((e or {}).get("text") or "")[:80], "kind": "interaction"})
        if kind is not None:
            trainers = tilekind.trainer_tiles(d)
            npcs_here = npc_tiles(d)
            for x, y in sorted(known_tiles(d)):
                k2 = tilekind.classify(d, tile_types, grass_ids, 0, x, y, None, npcs_here, trainers)
                if k2 == kind:
                    results.append({"map": mid, "x": x, "y": y, "kind": k2})
    if q.get("item") is not None:
        results.extend(_item_hits(data, str(q["item"]).lower()))
    seen = set()
    uniq = []
    for r in results:
        s = json.dumps(r, sort_keys=True)
        if s not in seen:
            seen.add(s)
            uniq.append(r)
    truncated = len(uniq) > MAX_RESULTS
    uniq = uniq[:MAX_RESULTS]
    return {"count": len(uniq), "truncated": truncated, "results": uniq,
            "query": {k: (str(v) if not isinstance(v, (int, float, bool, type(None))) else v) for k, v in sorted(q.items())}}
