"""A bump on an already-crossed map edge is a temp block, never a permanent wall (Cerulean (20,0) UP, 2026-11-13). ROM-free."""
from __future__ import annotations

import json
from types import SimpleNamespace

from pokeagent.explorer import press_interact
from pokeagent.explorer.memory import MapMemory

CER, R24 = 0x03, 0x23
KEY = "20,0,UP"


def _mem(tmp_path, crossed: bool, blocked=False):
    d = {"visited": {"20,0": 5}, "blocked": [KEY] if blocked else [], "warps": {KEY: [R24, 10, 35]} if crossed else {}}
    if crossed:
        d["warp_taken"] = {KEY: 296}
    p = tmp_path / "maps.json"; p.write_text(json.dumps({"maps": {str(CER): d}}))
    return MapMemory(p)


def test_one_bump_after_crossing_is_no_wall_and_expires(tmp_path):
    mem = _mem(tmp_path, crossed=True)
    before = (CER, 20, 0)
    res = mem.learn(before, "UP", before, confirmed=False)       # the 1849 trace: crossed, then the position did not change
    res2 = mem.learn(before, "UP", before, confirmed=True)       # even a confirmed repeat stays temporary
    assert "not a wall" in res and "not a wall" in res2
    assert KEY not in mem.m(CER)["blocked"] and not mem.m(CER).get("fails")
    ctx = SimpleNamespace(mem=mem, frame=1000)
    mem.temp_blocked[(CER, 20, -1)] = ctx.frame + press_interact.EDGE_BLOCK_FRAMES
    assert mem.temp_blocked[(CER, 20, -1)] > 1000
    mem.temp_blocked = {k: v for k, v in mem.temp_blocked.items() if v > 1000 + 300}   # after expiry
    assert not mem.temp_blocked and KEY not in mem.m(CER)["blocked"]
    assert "WARP" in mem.learn(before, "UP", (R24, 10, 35), confirmed=False)           # and the crossing still works


def test_never_crossed_wall_still_becomes_permanent(tmp_path):
    mem = _mem(tmp_path, crossed=False)
    before = (CER, 20, 0)
    mem.learn(before, "UP", before, confirmed=False)
    assert mem.learn(before, "UP", before, confirmed=False) == "blocked (confirmed)"
    assert KEY in mem.m(CER)["blocked"]


def test_stored_wall_on_a_crossed_edge_is_cleaned_on_load(tmp_path):
    assert KEY not in _mem(tmp_path, crossed=True, blocked=True).m(CER)["blocked"]
