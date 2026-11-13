"""The single entry the swarm merge calls for a family game: find disagreements, merge the rest, record who saw what."""
from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

from pokeagent.family import overlay as ov
from pokeagent.family import provenance as pv
from pokeagent.family import report as rp
from pokeagent.family.disagree import find_disagreements

_MOVES = ("warps", "jumps", "npcs")


def fold_agent_memory(shared: Path, dst: dict, agent: dict, game, merge: Callable, edits=None) -> dict:
    """Fold ``agent`` into ``dst`` (the loaded shared doc) as ``game``; ``merge(dst, src, edits=)`` is the
    existing merge_memory. Disagreeing warps/jumps/npcs go to the game's overlay, the rest merges as before.
    Returns {"overlay": n, "reported": n}. Idempotent."""
    prov, over = pv.load(shared), ov.load_overlay(shared, game.key)
    filtered, rows, changed_over = copy.deepcopy(agent), [], False
    for mid, am in (agent.get("maps") or {}).items():
        sm = (dst.get("maps") or {}).get(mid)
        found = find_disagreements(sm, am, game, mid) if sm else []
        omap = over["maps"].setdefault(mid, {})
        for d in found:
            sec, key, kind = d["section"], d["key"], d["kind"]
            if kind != "wall_suspect":
                if sec in _MOVES:
                    filtered["maps"][mid][sec].pop(key, None)
                    target = omap.setdefault(sec, {})
                    if target.get(key) != d["value"]:
                        target[key], changed_over = d["value"], True
                else:
                    lst = omap.setdefault("blocked_not", [])
                    if key not in lst:
                        lst.append(key)
                        changed_over = True
            rows.append({"game": game.key, "map": mid, "section": sec, "key": key, "kind": kind,
                         "shared": (sm or {}).get(sec, {}).get(key) if isinstance((sm or {}).get(sec), dict) else key,
                         "overlay": d["value"]})
        if not omap:
            over["maps"].pop(mid, None)
        for sec, key in pv.fact_keys(filtered["maps"][mid]):
            pv.record(prov, mid, sec, key, game.key, bool(sm) and key in (sm.get(sec) or []))
    merge(dst, filtered, edits=edits)
    if changed_over:
        ov.save_overlay(shared, game.key, over)
    pv.save(shared, prov)
    return {"overlay": sum(1 for r in rows if r["kind"] != "wall_suspect"), "reported": rp.append_new(shared, rows)}
