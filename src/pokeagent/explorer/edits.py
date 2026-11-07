"""Edit journal: ``runs/memory_edits.jsonl`` - surgery on map memory that survives agent saves.

One JSON line per edit: ``{"id", "ts", "op", "map", "key", "value", "note", "by", "prior"?}``.
Ops mutate the maps.json ``data`` dict; ``apply`` replays the journal in order and is pure and
idempotent, so ``MapMemory`` can fold it on load, again immediately before every ``save()``,
``reload_edits`` can fold it live, and the swarm merge can fold it after merging. An agent's
stale in-memory copy can never revert a recorded edit - the journal is re-applied on top of
whatever the agent thinks it knows.

``prior`` is an optional undo payload captured by ``prior_state`` at edit time; ``apply``
ignores it, ``undo`` uses it to restore exactly what the edit changed. The per-op mutations
live in ``edits_ops.py``; this module owns the file format, validation and the apply engine.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from pokeagent.explorer import edits_ops, legend

JOURNAL_NAME = "memory_edits.jsonl"
OPS = ("wall_add", "wall_remove", "warp_remove", "warp_add", "jump_add", "jump_remove",
       "interaction_clear", "npc_trainer", "npc_forget", "tile_kind", "visited_clear", "undo")
DIRECT_EDITS = OPS[:-1]  # every op except undo
DIRS = ("UP", "DOWN", "LEFT", "RIGHT")
KINDS = set(legend.GLYPHS) - {"you"}  # a tile_kind override may be any legend kind but the player
MAX_UNDO_DEPTH = 8


def journal_path_for(maps_path) -> Path:
    """The journal lives beside maps.json: runs/maps.json -> runs/memory_edits.jsonl."""
    return Path(maps_path).parent / JOURNAL_NAME


def read_journal(path) -> list[dict]:
    """All well-formed edit records in file order; missing file or bad lines are skipped."""
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def append_edit(path, *, op: str, map_id, key: str, value=None, note: str = "", by: str = "",
                prior=None) -> dict:
    """Append one edit line and return the record (with its fresh id)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"id": uuid.uuid4().hex[:12], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "op": op, "map": map_id, "key": key, "value": value, "note": note, "by": by}
    if prior is not None:
        rec["prior"] = prior
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


# --- validation / normalisation (shared by the CLI and the MCP tools) ---

def _edge_key(key: str) -> bool:
    parts = str(key).split(",")
    return len(parts) == 3 and parts[2] in DIRS


def _tile_key(key: str) -> bool:
    return len(str(key).split(",")) == 2


def _coords(value, n: int) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != n:
        return None
    try:
        return [int(v) for v in value]
    except (TypeError, ValueError):
        return None


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
    raise ValueError(f"npc_trainer value must be a bool, got {value!r}")


def prepare(op: str, map_id, key: str, value=None):
    """Validate and normalise an edit's fields; returns ``(map_id, key, value)``.

    ``undo`` is not a direct edit (it goes through the undo command), and ``tile_kind``
    takes a legend kind or nothing (nothing clears the override).
    """
    if op == "undo":
        raise ValueError("undo is not a direct edit; use the undo command")
    if op not in DIRECT_EDITS:
        raise ValueError(f"unknown op {op!r}; use one of {DIRECT_EDITS}")
    try:
        map_id = int(map_id)
    except (TypeError, ValueError):
        raise ValueError(f"map must be an integer, got {map_id!r}") from None
    key = str(key)
    if not key:
        raise ValueError("key must be non-empty")
    if op in ("wall_add", "wall_remove", "warp_remove", "jump_add", "jump_remove") and not _edge_key(key):
        raise ValueError(f"{op} key must be 'x,y,DIR' with DIR in {DIRS}, got {key!r}")
    if op == "interaction_clear" and not _edge_key(key):
        raise ValueError(f"interaction_clear key must be 'x,y,FACING', got {key!r}")
    if op in ("npc_trainer", "npc_forget", "tile_kind", "visited_clear") and not _tile_key(key):
        raise ValueError(f"{op} key must be 'x,y', got {key!r}")
    if op == "warp_add":
        dest = _coords(value, 3)
        if dest is None:
            raise ValueError("warp_add value must be [map, x, y]")
        value = dest
    elif op == "jump_add":
        dest = _coords(value, 2)
        if dest is None:
            raise ValueError("jump_add value must be [x, y]")
        value = dest
    elif op == "npc_trainer":
        value = _as_bool(value)
    elif op == "tile_kind":
        if value in (None, "clear", "none", "null"):
            value = None
        elif value not in KINDS:
            raise ValueError(f"tile_kind value must be a legend kind {sorted(KINDS)} or 'clear', got {value!r}")
    return map_id, key, value


# --- prior-state capture (what undo restores) ---

def prior_state(data: dict, op: str, map_id, key: str, value=None):
    """The state an undo must restore, captured from the *effective* data (journal applied)."""
    d = edits_ops.map_of(data, map_id)
    if op in ("wall_add", "wall_remove"):
        return key in ((d or {}).get("blocked") or [])
    if op == "warp_add":
        return {"warp": ((d or {}).get("warps") or {}).get(key),
                "bad": edits_ops.tombstoned(data, map_id, key)}
    if op == "warp_remove":
        return {"warp": ((d or {}).get("warps") or {}).get(key),
                "cand": ((d or {}).get("warp_cand") or {}).get(key),
                "taken": ((d or {}).get("warp_taken") or {}).get(key),
                "bad": edits_ops.tombstoned(data, map_id, key)}
    if op in ("jump_add", "jump_remove"):
        return ((d or {}).get("jumps") or {}).get(key)
    if op == "interaction_clear":
        return ((d or {}).get("interactions") or {}).get(key)
    if op == "npc_trainer":
        found = edits_ops.npcs_at(d, key)
        return {nid: bool(n.get("trainer")) for nid, n in found.items()} or None
    if op == "npc_forget":
        return edits_ops.npcs_at(d, key) or None
    if op == "tile_kind":
        return ((d or {}).get("tile_overrides") or {}).get(key)
    if op == "visited_clear":
        return ((d or {}).get("visited") or {}).get(key)
    return None


# --- apply engine: replay the journal in file order ---

def apply(data: dict, edits) -> dict:
    """Replay the journal over ``data`` in file order. Pure (no IO) and idempotent."""
    records = [e for e in (edits or []) if isinstance(e, dict)]
    by_id = {}
    for e in records:
        eid = e.get("id")
        if eid is not None and eid not in by_id:
            by_id[eid] = e
    for e in records:
        _apply_one(data, e, by_id, frozenset(), 0)
    return data


def _apply_one(data: dict, e: dict, by_id: dict, seen: frozenset, depth: int) -> None:
    if depth > MAX_UNDO_DEPTH:
        return
    if e.get("op") == "undo":
        tid = e.get("value")
        t = by_id.get(tid)
        eid = e.get("id")
        if t is not None and tid != eid and tid not in seen and eid not in seen:
            _resolve_undo(data, t, by_id, seen | {tid}, depth + 1)
        return
    fn = edits_ops.FORWARD.get(e.get("op"))
    if fn is not None:
        fn(data, e)


def _resolve_undo(data: dict, target: dict, by_id: dict, seen: frozenset, depth: int) -> None:
    """Apply the inverse of ``target``. If the target is itself an undo, re-apply its target."""
    if target.get("op") == "undo":
        tid = target.get("value")
        t = by_id.get(tid)
        if t is not None and tid not in seen and target.get("id") not in seen:
            _apply_one(data, t, by_id, seen | {tid}, depth + 1)
        return
    edits_ops.invert_edit(data, target)
