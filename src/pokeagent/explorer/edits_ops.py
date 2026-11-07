"""The data-mutating half of the edit journal: per-op forward functions and undo inversion.

``edits.py`` owns the journal file format, validation and the ``apply`` engine; this module
owns what each op does to a maps.json ``data`` dict. Everything here is pure (no IO) so
``apply`` stays replayable and idempotent. Helpers are shared with ``prior_state`` in
``edits.py`` - import them from here rather than duplicating.
"""
from __future__ import annotations


def map_of(data: dict, map_id) -> dict | None:
    return (data.get("maps") or {}).get(str(map_id))


def map_entry(data: dict, map_id, create: bool = True) -> dict | None:
    maps = data.setdefault("maps", {})
    mid = str(map_id)
    if mid not in maps:
        if not create:
            return None
        maps[mid] = {"visited": {}, "blocked": [], "warps": {}, "last_seen": 0}
    return maps[mid]


def tombstoned(data: dict, map_id, key: str) -> bool:
    return f"{map_id}:{key}" in (data.get("bad_warps") or [])


def add_tombstone(data: dict, map_id, key: str) -> None:
    bad = data.setdefault("bad_warps", [])
    ref = f"{map_id}:{key}"
    if ref not in bad:
        bad.append(ref)


def drop_tombstone(data: dict, map_id, key: str) -> None:
    bad = data.get("bad_warps")
    if bad:
        ref = f"{map_id}:{key}"
        if ref in bad:
            bad.remove(ref)


def npcs_at(d: dict | None, key: str) -> dict:
    """``{npc_id: entry}`` for NPCs whose last-seen tile is the 'x,y' key."""
    if not d:
        return {}
    parts = str(key).split(",")
    try:
        pos = [int(parts[0]), int(parts[1])]
    except (IndexError, ValueError):
        return {}
    return {nid: n for nid, n in (d.get("npcs") or {}).items() if n.get("last") == pos}


# --- forward ops ---

def _fw_wall_add(data, e):
    blocked = map_entry(data, e.get("map")).setdefault("blocked", [])
    if e.get("key") not in blocked:
        blocked.append(e.get("key"))


def _fw_wall_remove(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is not None and e.get("key") in (d.get("blocked") or []):
        d["blocked"].remove(e.get("key"))


def _fw_warp_remove(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is not None:
        for sect in ("warps", "warp_cand", "warp_taken"):
            (d.get(sect) or {}).pop(e.get("key"), None)
    add_tombstone(data, e.get("map"), e.get("key"))  # tombstone even for an unknown map: never relearn it


def _fw_warp_add(data, e):
    map_entry(data, e.get("map")).setdefault("warps", {})[e.get("key")] = e.get("value")
    drop_tombstone(data, e.get("map"), e.get("key"))  # surgery overrides the tombstone


def _fw_jump_add(data, e):
    map_entry(data, e.get("map")).setdefault("jumps", {})[e.get("key")] = e.get("value")


def _fw_jump_remove(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is not None:
        (d.get("jumps") or {}).pop(e.get("key"), None)


def _fw_interaction_clear(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is not None:
        (d.get("interactions") or {}).pop(e.get("key"), None)


def _fw_npc_trainer(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is None:
        return
    want = e.get("value")
    want = want if isinstance(want, bool) else str(want).strip().lower() in ("1", "true", "yes", "on")
    for npc in npcs_at(d, e.get("key")).values():
        npc["trainer"] = want


def _fw_npc_forget(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is None:
        return
    npcs = d.get("npcs")
    if not npcs:
        return
    for nid in [nid for nid in npcs_at(d, e.get("key"))]:
        npcs.pop(nid, None)


def _fw_tile_kind(data, e):
    d = map_entry(data, e.get("map"))
    ov = d.setdefault("tile_overrides", {})
    if e.get("value") is None:
        ov.pop(e.get("key"), None)
    else:
        ov[e.get("key")] = e.get("value")
    if not ov:
        d.pop("tile_overrides", None)


def _fw_visited_clear(data, e):
    d = map_entry(data, e.get("map"), create=False)
    if d is not None:
        (d.get("visited") or {}).pop(e.get("key"), None)


FORWARD = {"wall_add": _fw_wall_add, "wall_remove": _fw_wall_remove, "warp_remove": _fw_warp_remove,
           "warp_add": _fw_warp_add, "jump_add": _fw_jump_add, "jump_remove": _fw_jump_remove,
           "interaction_clear": _fw_interaction_clear, "npc_trainer": _fw_npc_trainer,
           "npc_forget": _fw_npc_forget, "tile_kind": _fw_tile_kind, "visited_clear": _fw_visited_clear}


# --- undo: restore the prior state the edit replaced ---

def _restore_table(d: dict | None, sect: str, key, prior):
    """Restore ``table[key]`` to ``prior`` (None removes it); creates the table only when needed."""
    if d is None:
        return
    table = d.get(sect)
    if table is None:
        if prior is None:
            return
        table = d[sect] = {}
    if prior is None:
        table.pop(key, None)
    else:
        table[key] = prior


def invert_edit(data: dict, e: dict) -> None:
    """Apply the inverse of journal edit ``e`` (restore its ``prior`` state).

    ``e`` is never an ``undo`` record: the apply engine intercepts those first.
    """
    op = e.get("op")
    prior = e.get("prior")
    mid, key = e.get("map"), e.get("key")
    d = map_of(data, mid)
    if op in ("wall_add", "wall_remove"):
        was = prior if isinstance(prior, bool) else op == "wall_remove"
        if d is not None:
            blocked = d.setdefault("blocked", [])
            if was and key not in blocked:
                blocked.append(key)
            elif not was and key in blocked:
                blocked.remove(key)
    elif op == "warp_add":
        p = prior if isinstance(prior, dict) else {}
        if d is not None:
            w = d.setdefault("warps", {})
            if p.get("warp") is None:
                w.pop(key, None)
            else:
                w[key] = p["warp"]
        if "bad" in p:
            (add_tombstone if p["bad"] else drop_tombstone)(data, mid, key)
    elif op == "warp_remove":
        p = prior if isinstance(prior, dict) else {}
        if d is not None:
            for sect, pk in (("warps", "warp"), ("warp_cand", "cand"), ("warp_taken", "taken")):
                if p.get(pk) is not None:
                    d.setdefault(sect, {})[key] = p[pk]
        if p.get("bad"):
            add_tombstone(data, mid, key)
        else:
            drop_tombstone(data, mid, key)
    elif op in ("jump_add", "jump_remove"):
        _restore_table(d, "jumps", key, prior)
    elif op == "interaction_clear":
        _restore_table(d, "interactions", key, prior)
    elif op == "visited_clear":
        _restore_table(d, "visited", key, prior)
    elif op == "tile_kind":
        if d is not None:
            ov = d.get("tile_overrides")
            if ov is None and prior is not None:
                ov = d["tile_overrides"] = {}
            if ov is not None:
                if prior is None:
                    ov.pop(key, None)
                else:
                    ov[key] = prior
                if not ov:
                    d.pop("tile_overrides", None)
    elif op == "npc_trainer":
        if d is not None and isinstance(prior, dict):
            npcs = d.get("npcs") or {}
            for nid, was in prior.items():
                if nid in npcs:
                    npcs[nid]["trainer"] = bool(was)
    elif op == "npc_forget":
        if d is not None and isinstance(prior, dict):
            npcs = d.setdefault("npcs", {})
            for nid, entry in prior.items():
                npcs[nid] = entry
