"""Brain query library, CLI, MCP tools, live-agent refusal and Q-table backups."""
import json
import sys
from pathlib import Path

import pytest

import pokeagent.brain as brain
from pokeagent.brain import fileops
from pokeagent.cli_brain import main as brain_main
from pokeagent.explorer import edits
from pokeagent.mcp_server import _Tools

ROOT = Path(__file__).resolve().parents[1]


def _data():
    return {
        "updated": "2026-01-01T00:00:00",
        "maps": {"1": {
            "visited": {"3,4": 2, "5,5": 1}, "blocked": ["3,4,UP", "9,9,LEFT"], "last_seen": 9,
            "warps": {"3,5,DOWN": [2, 0, 0]}, "warp_cand": {"4,4,LEFT": 1},
            "warp_taken": {"3,5,DOWN": 2}, "jumps": {"6,6,RIGHT": [8, 6]},
            "fails": {"7,7,UP": 2},
            "interactions": {"3,4,UP": {"count": 1, "text": "Hello there", "choices": ["YES"]}},
            "npcs": {"slot1:pic9": {"pic": 9, "slot": 1, "last": [4, 4], "trainer": True, "talked": 1}},
            "encounters": {"5,5": 3},
            "outcomes": {"5,5,UP": {"heal": {"n": 2, "progress": 1, "best": 4}}},
        }, "12": {"visited": {"0,0": 1}, "blocked": [], "warps": {}, "last_seen": 1}},
        "tile_types": {"0": {"01020304": {"solid": 5, "walkable": 0}}},
        "grass_ids": {"0": {"05060708": 2}},
        "bad_warps": ["1:4,4,LEFT"],
        "battle_lessons": {"rat": {"fights": 4, "wins": 3, "fled": 1, "turns": [3, 4], "hp_lost": [5, 7]}},
        "move_damage": {"tackle": [[10, 20]]},
        "beats": {"abc": {"buttons": ["A", "B"], "grade": 1, "replays": 0, "seen": 2}},
        "items": [{"item": "POTION", "id": 13, "map": 1, "at": [4, 4], "delta": -1, "text": "Got POTION!"}],
    }


def _maps_file(tmp_path, data=None):
    p = tmp_path / "maps.json"
    p.write_text(json.dumps(data if data is not None else _data()))
    return p


# --- brain query functions ---

def test_maps_summary_counts():
    s = brain.maps_summary(_data())
    assert s["maps"]["1"]["visited"] == 2 and s["maps"]["1"]["warps"] == 1
    assert s["maps"]["12"]["visited"] == 1
    assert s["totals"]["maps"] == 2 and s["bad_warps"] == 1 and s["beats"] == 1


def test_map_view_rows_overlay_and_legend():
    v = brain.map_view(_data(), 1, "visits")
    assert v["map"] == "1" and v["width"] > 0 and len(v["rows"]) == v["height"]
    assert v["overlay"]["cells"]["3,4"] == 2 and v["overlay"]["cells"]["5,5"] == 1
    assert "legend" in v and v["tiles_known"] > 0
    with pytest.raises(ValueError):
        brain.map_view(_data(), 1, "bogus")
    assert brain.map_view(_data(), 99)["error"] == "map not in memory"


def test_tile_facts_collects_everything():
    data = _data()
    journal = [e for e in [
        {"id": "w1", "op": "wall_add", "map": 1, "key": "3,4,UP", "value": None},
        {"id": "w2", "op": "warp_add", "map": 1, "key": "9,9,UP", "value": [1, 3, 4]},
        {"id": "u1", "op": "undo", "map": 1, "key": "x", "value": "w2"},
    ]]
    f = brain.tile_facts(data, 1, 3, 4, edits=journal)
    assert f["kind"] == "interaction" and f["visited"] == 2 and f["blocked_from"] == ["UP"]
    assert f["warps"] == {}  # the warp lives at (3,5), one tile south
    assert f["interactions"]["3,4,UP"]["text"] == "Hello there"
    assert any(e["id"] == "w1" for e in f["edits"])
    f2 = brain.tile_facts(data, 1, 3, 4)  # no journal -> no edits key
    assert "edits" not in f2
    # warp_add targets tile (3,4): both the edit and its undo touch it
    f3 = brain.tile_facts(data, 1, 3, 4, edits=journal)
    assert {e["id"] for e in f3["edits"]} == {"w1", "w2", "u1"}


def test_find_by_kind_text_item_warp():
    r = brain.find(_data(), {"kind": "warp", "map": 1})
    assert r["count"] == 1 and (r["results"][0]["x"], r["results"][0]["y"]) == (3, 5)
    r = brain.find(_data(), {"text": "hello"})
    assert r["results"] and r["results"][0]["text"] == "Hello there"
    r = brain.find(_data(), {"item": "potion"})
    assert r["results"][0]["item"] == "POTION"
    r = brain.find(_data(), {"warps_to": 2})
    assert r["count"] == 1 and r["results"][0]["to"] == [2, 0, 0]
    r = brain.find(_data(), {"kind": "trainer", "map": 1})
    assert any(x["x"] == 4 and x["y"] == 4 for x in r["results"])


def test_diff_snapshots():
    a = _data()
    b = json.loads(json.dumps(a))
    b["maps"]["1"]["visited"]["9,9"] = 5
    b["maps"]["2"] = {"visited": {"0,0": 1}}
    del b["maps"]["12"]
    d = brain.diff(a, b)
    assert d["maps"]["1"]["fields"]["visited"]["added"]["count"] == 1
    assert d["maps"]["2"]["added"] is True and d["maps"]["12"]["removed"] is True


def test_lessons_kinds():
    all_l = brain.lessons(_data())
    assert all_l["battle"]["rat"]["win_rate"] == 0.75
    assert all_l["damage"]["move_damage"]["entries"] == 1
    assert all_l["tiles"]["tile_types"]["blocks"] == 1
    assert all_l["beats"]["count"] == 1
    assert brain.lessons(_data(), "battle") == {"battle": all_l["battle"]}
    with pytest.raises(ValueError):
        brain.lessons(_data(), "bogus")


def _q_file(tmp_path):
    obs = "(0, 5, 6, 0, 0, 0, 20, 3)"
    p = tmp_path / "q_test.json"
    p.write_text(json.dumps({"version": 2, "schema": "s", "actions": 6,
                             "table": {obs: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}}))
    return p


def test_q_summary_and_state(tmp_path):
    p = _q_file(tmp_path)
    s = brain.q_summary(p)
    assert s["states"] == 1 and s["top"][0]["best"] == "B"  # 0.6 is index 5 -> BUTTONS[5]='B'
    st = brain.q_state(p, "(0, 5, 6, 0, 0, 0, 20, 3)")
    assert st["visited"] and st["q"]["B"] == 0.6
    assert brain.q_state(p, "(9, 9, 9, 0, 0, 0, 1, 1)")["visited"] is False


# --- CLI ---

def _run(argv):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = brain_main(argv)
    return rc, buf.getvalue()


def test_cli_maps_and_map(tmp_path, capsys):
    maps = _maps_file(tmp_path)
    rc, out = _run(["maps", "--maps", str(maps)])
    assert rc == 0
    s = json.loads(out)
    assert s["totals"]["maps"] == 2
    rc, out = _run(["map", "1", "--maps", str(maps), "--overlay", "encounters"])
    v = json.loads(out)
    assert v["overlay"]["cells"]["5,5"] == 3
    rc, out = _run(["map", "1", "--maps", str(maps), "--text"])
    assert "map 1" in out


def test_cli_tile_find_diff_lessons(tmp_path):
    maps = _maps_file(tmp_path)
    rc, out = _run(["tile", "1", "3", "4", "--maps", str(maps)])
    f = json.loads(out)
    assert f["visited"] == 2 and f["interactions"]["3,4,UP"]["text"] == "Hello there"
    rc, out = _run(["find", "--maps", str(maps), "--kind", "warp"])
    assert json.loads(out)["count"] == 1
    other = tmp_path / "other.json"
    other.write_text(json.dumps(_data()))
    rc, out = _run(["diff", str(maps), str(other)])
    assert json.loads(out)["maps"] == {}
    rc, out = _run(["lessons", "--maps", str(maps), "battle"])
    assert "battle" in json.loads(out)


def test_cli_edit_edits_undo_apply(tmp_path):
    maps = _maps_file(tmp_path)
    rc, out = _run(["edit", "wall_add", "1", "8,8,UP", "--maps", str(maps),
                    "--note", "surgery", "--by", "test"])
    assert rc == 0 and json.loads(out)["ok"]
    journal = edits.read_journal(fileops.journal_for(maps))
    assert journal[-1]["op"] == "wall_add" and journal[-1]["prior"] is False
    eid = journal[-1]["id"]
    rc, out = _run(["edits", "--maps", str(maps)])
    assert json.loads(out)["count"] == 1
    rc, out = _run(["undo", eid, "--maps", str(maps)])
    assert json.loads(out)["ok"]
    data, _ = fileops.effective_data(maps)  # wall_add + undo net to zero
    assert "8,8,UP" not in data["maps"]["1"]["blocked"]
    rc, out = _run(["apply", "--maps", str(maps), "--backup"])
    res = json.loads(out)
    assert res["ok"] and res["applied"] == 2
    assert Path(res["backup"]).is_file()
    folded = json.loads(maps.read_text())
    assert "8,8,UP" not in folded["maps"]["1"]["blocked"]


def test_cli_apply_refuses_live_agent(tmp_path):
    maps = _maps_file(tmp_path)
    edits.append_edit(fileops.journal_for(maps), op="wall_add", map_id=1, key="8,8,UP", note="x")
    agents = maps.parent / "agents"
    agents.mkdir()
    (agents / "a.json").write_text(json.dumps({"id": "a", "pid": __import__("os").getpid()}))
    rc, out = _run(["apply", "--maps", str(maps), "--backup"])
    assert rc == 1 and "alive" in out
    assert "8,8,UP" not in json.loads(maps.read_text())["maps"]["1"]["blocked"]


def test_cli_q_set_and_patch_backup(tmp_path):
    p = _q_file(tmp_path)
    rc, out = _run(["q", str(p), "--set", "(0, 5, 6, 0, 0, 0, 20, 3)", "A", "-5.0"])
    res = json.loads(out)
    assert res["ok"] and Path(res["backup"]).is_file()
    assert brain.q_state(p, "(0, 5, 6, 0, 0, 0, 20, 3)")["q"]["A"] == -5.0
    rc, out = _run(["q", str(p)])
    assert json.loads(out)["states"] == 1
    obs14 = "(0, 1, 2, 0, 0, 0, 20, 3, 1, 1, 0, 0, 0, 3)"  # OVERWORLD/START-menu, option 3 = SAVE cursor
    p2 = tmp_path / "q_patch.json"
    p2.write_text(json.dumps({"version": 2, "schema": "s", "actions": 6,
                              "table": {obs14: [9.0] * 6, "(0,1,2,0,0,0,1,1)": [1.0] * 6}}))
    rc, out = _run(["q", str(p2), "--patch-save"])
    assert json.loads(out)["patched"] == 1
    row = brain.q_state(p2, obs14)["q"]
    assert row["A"] == -2.0 and row["B"] == 9.0


def test_brain_help_parses():
    from pokeagent import cli
    with pytest.raises(SystemExit) as exc:
        cli.main(["brain", "--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit) as exc:
        brain_main(["--help"])
    assert exc.value.code == 0


# --- MCP brain tools (direct calls, same callables build_server registers) ---

@pytest.fixture
def tools(tmp_path):
    _maps_file(tmp_path)
    return _Tools(thread=None, runs_dir=tmp_path / "mcp", maps_path=tmp_path / "maps.json")


def test_mcp_brain_reads(tools):
    assert tools.brain_maps()["totals"]["maps"] == 2
    v = tools.brain_map(1, "encounters")
    assert v["overlay"]["cells"]["5,5"] == 3
    f = tools.brain_tile(1, 3, 4)
    assert f["visited"] == 2
    assert tools.brain_find(kind="warp")["count"] == 1
    assert tools.brain_lessons("battle")["battle"]["rat"]["wins"] == 3


def test_mcp_brain_edit_and_undo(tools, tmp_path):
    out = tools.brain_edit("wall_add", 1, "8,8,UP", "surgery", by="mcp")
    assert out["ok"] and out["edit"]["op"] == "wall_add"
    eid = out["edit"]["id"]
    data = tools._brain_data()
    assert "8,8,UP" in data["maps"]["1"]["blocked"]
    assert tools.brain_undo(eid)["ok"]
    data = tools._brain_data()
    assert "8,8,UP" not in data["maps"]["1"]["blocked"]
    assert "error" in tools.brain_edit("bogus", 1, "1,1", "n")
    assert "error" in tools.brain_undo("nonexistent")
