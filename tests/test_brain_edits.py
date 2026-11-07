"""Edit journal: every op, idempotence, undo inversion, and survival across save/merge."""
import json
import sys
from pathlib import Path

import pytest

from pokeagent.explorer import edits
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer import tilekind


def _data():
    return {"maps": {"1": {
        "visited": {"3,4": 2, "5,5": 1}, "blocked": ["3,4,UP"], "last_seen": 9,
        "warps": {"3,5,DOWN": [2, 0, 0]}, "warp_cand": {"4,4,LEFT": 1},
        "warp_taken": {"3,5,DOWN": 2},
        "jumps": {"6,6,RIGHT": [8, 6]}, "fails": {"7,7,UP": 2},
        "interactions": {"3,4,UP": {"count": 1, "text": "HI"}},
        "npcs": {"slot1:pic9": {"pic": 9, "slot": 1, "last": [4, 4], "trainer": False, "talked": 1}},
        "encounters": {"5,5": 3}, "outcomes": {"5,5,UP": {"g1": {"n": 2, "progress": 1, "best": 4}}},
    }}}


def _rec(op, key, value=None, prior=None, rid="e1"):
    e = {"id": rid, "op": op, "map": 1, "key": key, "value": value}
    if prior is not None:
        e["prior"] = prior
    return e


def _map(data):
    return data["maps"]["1"]


@pytest.mark.parametrize("op,key,value,check", [
    ("wall_add", "9,9,LEFT", None, lambda d: "9,9,LEFT" in _map(d)["blocked"]),
    ("wall_remove", "3,4,UP", None, lambda d: "3,4,UP" not in _map(d)["blocked"]),
    ("warp_remove", "3,5,DOWN", None, lambda d: "3,5,DOWN" not in _map(d)["warps"]
        and "1:3,5,DOWN" in d["bad_warps"]),
    ("warp_add", "8,8,UP", [2, 1, 1], lambda d: _map(d)["warps"]["8,8,UP"] == [2, 1, 1]),
    ("jump_add", "1,1,DOWN", [1, 3], lambda d: _map(d)["jumps"]["1,1,DOWN"] == [1, 3]),
    ("jump_remove", "6,6,RIGHT", None, lambda d: "6,6,RIGHT" not in _map(d)["jumps"]),
    ("interaction_clear", "3,4,UP", None, lambda d: "3,4,UP" not in _map(d)["interactions"]),
    ("npc_trainer", "4,4", True, lambda d: _map(d)["npcs"]["slot1:pic9"]["trainer"] is True),
    ("npc_forget", "4,4", None, lambda d: "slot1:pic9" not in _map(d)["npcs"]),
    ("tile_kind", "3,4", "wall", lambda d: _map(d)["tile_overrides"]["3,4"] == "wall"),
    ("visited_clear", "3,4", None, lambda d: "3,4" not in _map(d)["visited"]),
])
def test_every_direct_op(op, key, value, check):
    data = edits.apply(_data(), [_rec(op, key, value)])
    assert check(data), op


def test_apply_is_idempotent():
    journal = [_rec("wall_add", "9,9,LEFT"), _rec("warp_remove", "3,5,DOWN"),
               _rec("tile_kind", "5,5", "encounter")]
    once = edits.apply(_data(), journal)
    twice = edits.apply(json.loads(json.dumps(once)), journal)
    assert once == twice


def test_undo_restores_prior_state():
    data = _data()
    wall = _rec("wall_add", "9,9,LEFT", prior=False, rid="a")
    warp = _rec("warp_remove", "3,5,DOWN", prior={"warp": [2, 0, 0], "cand": None, "taken": 2, "bad": False}, rid="b")
    vis = _rec("visited_clear", "3,4", prior=2, rid="c")
    undo = lambda rid: {"id": f"u-{rid}", "op": "undo", "map": 1, "key": "k", "value": rid}
    edits.apply(data, [wall, warp, vis, undo("a"), undo("b"), undo("c")])
    assert "9,9,LEFT" not in _map(data)["blocked"]
    assert _map(data)["warps"]["3,5,DOWN"] == [2, 0, 0]
    assert _map(data)["warp_taken"]["3,5,DOWN"] == 2
    assert _map(data)["visited"]["3,4"] == 2
    assert "1:3,5,DOWN" not in data.get("bad_warps", [])


def test_undo_without_prior_falls_back():
    wall = _rec("wall_add", "9,9,LEFT")  # no prior recorded
    undo = {"id": "u", "op": "undo", "map": 1, "key": "k", "value": "e1"}
    data = edits.apply(_data(), [wall, undo])  # undo resolves its target within the same replay
    assert "9,9,LEFT" not in _map(data)["blocked"]


def test_prepare_validates():
    with pytest.raises(ValueError):
        edits.prepare("undo", 1, "1,1", None)
    with pytest.raises(ValueError):
        edits.prepare("warp_add", 1, "1,1,UP", [2, 0])  # needs [map,x,y]
    with pytest.raises(ValueError):
        edits.prepare("wall_add", 1, "1,1", None)  # edge key needs DIR
    with pytest.raises(ValueError):
        edits.prepare("tile_kind", 1, "1,1", "bogus")
    assert edits.prepare("tile_kind", 1, "1,1", "clear")[2] is None
    assert edits.prepare("npc_trainer", 1, "1,1", "yes")[2] is True


def test_read_append_roundtrip(tmp_path):
    j = tmp_path / "memory_edits.jsonl"
    j.write_text('{"bad json"\n[1,2]\n{"id":"x","op":"wall_add","map":1,"key":"1,1,UP"}\n')
    recs = edits.read_journal(j)
    assert len(recs) == 1 and recs[0]["id"] == "x"
    new = edits.append_edit(j, op="wall_add", map_id=1, key="2,2,UP", note="n", by="t")
    assert new["id"] and len(edits.read_journal(j)) == 2


def _write_maps(path, data):
    path.write_text(json.dumps(data))
    return path


def test_mapmemory_load_and_save_reapply_journal(tmp_path):
    maps = _write_maps(tmp_path / "maps.json", _data())
    edits.append_edit(edits.journal_path_for(maps), op="wall_add", map_id=1, key="9,9,LEFT",
                      prior=False, note="surgery")
    mem = MapMemory(maps)
    assert "9,9,LEFT" in mem.data["maps"]["1"]["blocked"]
    # a stale in-memory copy that 'forgets' the edit must not revert it on save
    mem.data["maps"]["1"]["blocked"].remove("9,9,LEFT")
    mem.save()
    saved = json.loads(maps.read_text())
    assert "9,9,LEFT" in saved["maps"]["1"]["blocked"]


def test_apply_edits_live_reload(tmp_path):
    maps = _write_maps(tmp_path / "maps.json", _data())
    mem = MapMemory(maps)
    assert mem.apply_edits() == 0
    edits.append_edit(edits.journal_path_for(maps), op="visited_clear", map_id=1, key="3,4",
                      prior=2, note="surgery")
    assert mem.apply_edits() == 1
    assert "3,4" not in mem.data["maps"]["1"]["visited"]


def test_tile_kind_override_wins_in_classify():
    d = _data()["maps"]["1"]
    d["visited"]["3,4"] = 1  # visited would otherwise classify walkable-ish
    assert tilekind.classify(d, {}, {}, 0, 3, 4, None, set(), {}) != "wall"
    d["tile_overrides"] = {"3,4": "wall"}
    assert tilekind.classify(d, {}, {}, 0, 3, 4, None, set(), {}) == "wall"


def test_swarm_merge_reapplies_journal(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import swarm  # noqa: E402
    dst = {"maps": {}}
    src = _data()
    journal = [_rec("warp_remove", "3,5,DOWN", prior={"warp": [2, 0, 0], "cand": None, "taken": 2, "bad": False})]
    swarm.merge_memory(dst, src, edits=journal)
    assert "3,5,DOWN" not in dst["maps"]["1"]["warps"]
    assert "1:3,5,DOWN" in dst["bad_warps"]


def test_swarm_merge_blackout_tax_is_max_per_goal(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import swarm  # noqa: E402
    dst = {"maps": {}, "blackout_tax": {"A": {"steps": 3}}}
    src = {"maps": {}, "blackout_tax": {
        "A": {"steps": 2},        # lower than the shared copy: the max (3) wins, never summed (5)
        "B": {"steps": 1},        # only in the agent: copied
        "Z": {"steps": 0},        # zero: dropped
        "M": {"steps": "x"},      # malformed value: ignored
        "N": 5,                   # malformed entry: ignored
    }}
    swarm.merge_memory(dst, src)
    assert dst["blackout_tax"] == {"A": {"steps": 3}, "B": {"steps": 1}}
    # the other direction: the agent's higher count replaces the shared one
    dst2 = {"maps": {}, "blackout_tax": {"A": {"steps": 1}}}
    swarm.merge_memory(dst2, {"maps": {}, "blackout_tax": {"A": {"steps": 4}}})
    assert dst2["blackout_tax"] == {"A": {"steps": 4}}


def test_mapmemory_blackout_tax_roundtrip(tmp_path):
    maps = _write_maps(tmp_path / "maps.json", _data())
    mem = MapMemory(maps)
    mem.data["blackout_tax"] = {"rival_ss_anne": {"steps": 3}}
    mem.save()
    assert json.loads(maps.read_text())["blackout_tax"] == {"rival_ss_anne": {"steps": 3}}
    reloaded = MapMemory(maps)
    assert reloaded.data["blackout_tax"] == {"rival_ss_anne": {"steps": 3}}
