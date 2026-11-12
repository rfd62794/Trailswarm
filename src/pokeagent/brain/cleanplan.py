"""Clean planner: turn a maps.json document into the journal edits that strip playthrough state,
battle/menu noise and contradictory typing from its notes.

Pure: ``plan_clean(doc)`` reads the effective data (journal already applied), never mutates it and
never writes; the ``brain clean`` command appends the plan to the edit journal. The rules are listed
in ``docs/MEMORY_FACTS.md`` ("Rules ``brain clean`` applies"). Planned edits carry a reason code in
``note`` and no dialogue.
"""
from __future__ import annotations

from collections import defaultdict

from pokeagent.explorer.note_filter import first_noise, text_of


def _npc_tile(n: dict) -> str | None:
    last = n.get("last")
    if isinstance(last, list) and len(last) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in last):
        return f"{last[0]},{last[1]}"
    return None


def _has_pc_text(e: dict) -> bool:
    low = text_of(e).lower()
    return "turned on" in low and "the pc" in low


def _contradicting_facings(inters: dict) -> set:
    """Untyped facings with PC text on a tile where exactly one PC-text facing is typed ``pc``."""
    by_tile: dict = defaultdict(list)
    for key, e in inters.items():
        if isinstance(e, dict) and len(str(key).split(",")) == 3 and _has_pc_text(e):
            by_tile[",".join(str(key).split(",")[:2])].append(key)
    out = set()
    for keys in by_tile.values():
        typed = [k for k in keys if inters[k].get("type") == "pc"]
        if len(keys) >= 2 and len(typed) == 1:
            out.update(k for k in keys if k not in typed)
    return out


def _npc_needs(r: dict) -> list:
    out = []
    if "done" in r:
        out.append(("npc_state_clear", "done", "playthrough_state_done"))
    reason = first_noise(r)
    if reason:
        out.append(("npc_prune", "battle_menu", reason))
    return out


def _plan_map(mid, m: dict) -> list:
    plan = []
    inters = m.get("interactions") if isinstance(m.get("interactions"), dict) else {}
    contra = _contradicting_facings(inters)
    for key, e in inters.items():
        if not isinstance(e, dict) or len(str(key).split(",")) != 3:
            continue
        if key in contra:
            plan.append(("interaction_clear", key, None, "contradicts_typed_pc"))
            continue
        if "done" in e:
            plan.append(("interaction_state_clear", key, "done", "playthrough_state_done"))
        if "type" in e and len(e.get("type_votes") or {}) > 1:
            plan.append(("interaction_state_clear", key, "type", "conflicting_type_votes"))
        reason = first_noise(e)
        if reason:
            plan.append(("interaction_prune", key, "battle_menu", reason))
    npcs = m.get("npcs") if isinstance(m.get("npcs"), dict) else {}
    seen = set()
    for nid in sorted(npcs):
        n = npcs[nid]
        r = n.get("results") if isinstance(n, dict) else None
        tile = _npc_tile(n) if isinstance(r, dict) else None
        if tile is None:
            continue
        for op, value, reason in _npc_needs(r):
            if (op, tile, value) not in seen:
                seen.add((op, tile, value))
                plan.append((op, tile, value, reason))
    return [{"op": op, "map": int(mid), "key": key, "value": value, "note": reason}
            for op, key, value, reason in plan]


def _maps(doc: dict) -> dict:
    maps = doc.get("maps")
    return {mid: m for mid, m in maps.items() if str(mid).lstrip("-").isdigit() and isinstance(m, dict)} \
        if isinstance(maps, dict) else {}


def plan_clean(doc: dict) -> list[dict]:
    """Planned edits ``{"op", "map", "key", "value", "note"}``, sorted by map id, key, op (then value)."""
    plan = [p for mid, m in _maps(doc).items() for p in _plan_map(mid, m)]
    return sorted(plan, key=lambda p: (p["map"], p["key"], p["op"], str(p["value"])))


def unreachable_npcs(doc: dict) -> int:
    """NPCs that a rule would edit but that have no usable ``last`` tile (no op can reach them)."""
    n_skipped = 0
    for m in _maps(doc).values():
        for n in (m.get("npcs") or {}).values() if isinstance(m.get("npcs"), dict) else ():
            r = n.get("results") if isinstance(n, dict) else None
            if isinstance(r, dict) and _npc_tile(n) is None and _npc_needs(r):
                n_skipped += 1
    return n_skipped
