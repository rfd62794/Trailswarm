"""Library entries as Go-Explore cells: one cell per (checkpoint-or-segment, team build).

``to_archive`` turns the statelib index into an ``Archive`` whose cells the pickers sample: the archive's
own ``offer`` keeps the better state per cell, and ``n_seen`` comes from the tries file
``runs/states/build_tries.json`` so rarely-tried builds draw more weight. Only ``clean`` entries become
cells (``unknown`` only when ``allow_unknown``); a ``violation`` entry never does, so no picker built on
this archive can hand a violating state to a run. Tries are recorded once per ingested attempt by
``record_try`` (tools/seg_ingest) - a plain increment, not a rebuild, so the file is cheap to update.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pokeagent import statefp
from pokeagent.goexplore.archive import Archive, Entry
from pokeagent.goexplore.store import atomic_write
from pokeagent.segment_names import state_goal

TRIES = Path("runs/states/build_tries.json")
VERSION = 1
NO_STEPS = 10 ** 12   # a state with no recorded step count ranks as the slowest of its cell


def cell_id(e: dict) -> str:
    """The cell an entry belongs to: ``<name>|<build>`` for a checkpoint, ``leg:<segment>|<build>`` for a leg."""
    b = e.get("build") or "unknown"
    return f"leg:{e.get('segment')}|{b}" if e.get("tier") == "leg" else f"{e.get('name')}|{b}"


def is_cell(e: dict, allow_unknown: bool = False) -> bool:
    """True when the entry may be a cell: verdict ``clean`` (or ``unknown`` when explicitly allowed).
    A ``violation`` verdict never becomes a cell."""
    v = e.get("verdict")
    return v == "clean" or (allow_unknown and v == "unknown")


def _read_doc(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("cells"), dict):
            return {"v": VERSION, "cells": d["cells"]}
    except (OSError, ValueError):
        pass
    return {"v": VERSION, "cells": {}}


def read_tries(root: Path | str) -> dict:
    """``{cid: {"tries", "solves", "last"}}`` from the tries file; empty on a missing or malformed file."""
    return _read_doc(Path(root) / TRIES)["cells"]


def record_try(root: Path | str, cid: str, solved: bool) -> None:
    """One attempt against a cell: tries += 1, solves += solved, last = now. Never raises into ingest."""
    try:
        p = Path(root) / TRIES
        doc = _read_doc(p)
        c = doc["cells"].setdefault(cid, {"tries": 0, "solves": 0, "last": ""})
        c["tries"] = int(c.get("tries") or 0) + 1
        c["solves"] = int(c.get("solves") or 0) + bool(solved)
        c["last"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(p, json.dumps(doc, indent=1))
    except Exception:  # noqa: BLE001 - tries bookkeeping must never break an ingest
        pass


def tries_of(tries: dict, cid: str) -> int:
    """Times a cell was attempted; the value may be the full record or a bare count."""
    t = (tries or {}).get(cid)
    n = t.get("tries") if isinstance(t, dict) else t
    return int(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else 0


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _goal_idx(e: dict, goals_index: dict) -> int:
    """The GOALS index this cell sits at: the checkpoint's own index; a leg takes its segment's start index
    (the goal's first checkpoint - piece checkpoints resolve to the last completed whole goal)."""
    if e.get("tier") == "leg":
        seg = str(e.get("segment") or "")
        name = seg if "@" in seg or not seg else f"{seg}@end"   # state_goal('g@end') = the goal before g
    else:
        name = str(e.get("name") or "")
    return goals_index.get(state_goal(name), -1) if name else -1


def _hp(e: dict) -> float:
    """Party HP fraction: the entry's ``hp`` field when present, else the state's fingerprint sidecar."""
    h = _num(e.get("hp"))
    if h is not None:
        return h
    try:
        return statefp.party_hp_fraction(statefp.read(e.get("state") or "") or {})
    except Exception:  # noqa: BLE001 - an unreadable sidecar is a state at unknown health, not an error
        return 0.0


def to_archive(entries, goals_index, tries=None, root=".", allow_unknown: bool = False) -> Archive:
    """One ``Entry`` per cell, holding the cell's best state (``offer`` keeps the better score).
    ``goals_index`` maps a checkpoint/goal name to its GOALS index; ``tries`` defaults to the tries file."""
    tries = read_tries(root) if tries is None else (tries or {})
    a = Archive()
    for e in entries or ():
        if not isinstance(e, dict) or not is_cell(e, allow_unknown):
            continue
        cid, m = cell_id(e), e.get("metrics") or {}
        s = _num(m.get("steps"))
        a.offer(Entry(cid=cid, state=str(e.get("state") or ""), goals=_goal_idx(e, goals_index),
                      steps=int(s) if s is not None else NO_STEPS,
                      hp=_hp(e), n_seen=tries_of(tries, cid), parent=e.get("parent")))
    return a
