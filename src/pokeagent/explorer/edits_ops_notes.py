"""Journal ops on note state: ``interaction_state_clear``, ``npc_state_clear``, ``interaction_prune``
and ``npc_prune`` - their forward mutation, undo payload and inversion.

Registered in ``edits_ops.FORWARD`` / ``edits_ops.invert_edit`` and ``edits.prior_state``. Pure (no
IO); a missing map, entry or field is a no-op. NPCs are matched by their ``last`` tile only (as
``npc_forget`` does), so an NPC with no ``last`` is never reached.
"""
from __future__ import annotations

import copy

from pokeagent.explorer import note_filter

OPS = ("interaction_state_clear", "npc_state_clear", "interaction_prune", "npc_prune")
STATE_FIELDS = {"done": ("done",), "type": ("type", "type_conf", "type_why")}  # type_votes stays: the evidence
EDGE_VALUES = {"interaction_state_clear": ("done", "type"), "interaction_prune": ("battle_menu",)}
TILE_VALUES = {"npc_state_clear": ("done",), "npc_prune": ("battle_menu",)}


def _helpers():
    from pokeagent.explorer import edits_ops  # edits_ops imports this module: resolve at call time
    return edits_ops


def _entry(data: dict, e: dict) -> dict | None:
    d = _helpers().map_of(data, e.get("map"))
    entry = ((d or {}).get("interactions") or {}).get(e.get("key"))
    return entry if isinstance(entry, dict) else None


def _results_at(data: dict, e: dict) -> dict:
    """``{npc_id: results}`` for NPCs at the edit's tile whose ``results`` is a dict."""
    ops = _helpers()
    found = ops.npcs_at(ops.map_of(data, e.get("map")), e.get("key"))
    return {nid: n["results"] for nid, n in found.items() if isinstance(n.get("results"), dict)}


def _clear_fields(entry: dict, fields) -> dict | None:
    removed = {f: entry.pop(f) for f in fields if f in entry}
    return removed or None


# --- forward ---

def fw_interaction_state_clear(data, e):
    entry = _entry(data, e)
    if entry is not None:
        _clear_fields(entry, STATE_FIELDS.get(e.get("value"), ()))


def fw_npc_state_clear(data, e):
    for res in _results_at(data, e).values():
        res.pop("done", None)


def fw_interaction_prune(data, e):
    entry = _entry(data, e)
    if entry is not None:
        note_filter.prune_note(entry)


def fw_npc_prune(data, e):
    for res in _results_at(data, e).values():
        note_filter.prune_note(res)


FORWARD = {"interaction_state_clear": fw_interaction_state_clear, "npc_state_clear": fw_npc_state_clear,
           "interaction_prune": fw_interaction_prune, "npc_prune": fw_npc_prune}


# --- undo payload (captured from the effective data, never mutating it) ---

def prior(data: dict, op: str, map_id, key: str, value=None):
    e = {"map": map_id, "key": key, "value": value}
    if op == "interaction_state_clear":
        entry = _entry(data, e)
        return None if entry is None else _clear_fields(copy.deepcopy(entry), STATE_FIELDS.get(value, ()))
    if op == "npc_state_clear":
        return {nid: r["done"] for nid, r in _results_at(data, e).items() if "done" in r} or None
    if op == "interaction_prune":
        entry = _entry(data, e)
        return None if entry is None else note_filter.prune_note(copy.deepcopy(entry))
    if op == "npc_prune":
        out = {nid: note_filter.prune_note(copy.deepcopy(r)) for nid, r in _results_at(data, e).items()}
        return {nid: p for nid, p in out.items() if p is not None} or None
    return None


# --- inversion ---

def _restore_note(entry: dict, payload: dict) -> None:
    """Restore ``text``/``pages`` from the payload; a key the payload lacks is deleted."""
    for k in ("text", "pages"):
        if k in payload:
            entry[k] = copy.deepcopy(payload[k])
        else:
            entry.pop(k, None)


def invert(data: dict, e: dict) -> None:
    op, p = e.get("op"), e.get("prior")
    if not isinstance(p, dict):
        return
    if op == "interaction_state_clear":
        entry = _entry(data, e)
        if entry is not None:
            entry.update(copy.deepcopy(p))
    elif op == "interaction_prune":
        entry = _entry(data, e)
        if entry is not None:
            _restore_note(entry, p)
    elif op in ("npc_state_clear", "npc_prune"):
        ops = _helpers()
        npcs = (ops.map_of(data, e.get("map")) or {}).get("npcs") or {}
        for nid, was in p.items():
            res = (npcs.get(nid) or {}).get("results")
            if not isinstance(res, dict):
                continue
            if op == "npc_state_clear":
                res["done"] = copy.deepcopy(was)
            elif isinstance(was, dict):
                _restore_note(res, was)
