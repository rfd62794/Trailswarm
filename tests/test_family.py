"""Family shared memory: gating, provenance, disagreements, overlay-first reads, both-ways fold, kb overlay."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import swarm_merge  # noqa: E402

from pokeagent.family import effective_memory, family_active, fold_agent_memory  # noqa: E402
from pokeagent.family import kb_overlay, provenance as pv  # noqa: E402
from pokeagent.family.disagree import find_disagreements  # noqa: E402
from pokeagent.family.overlay import load_overlay, overlay_path  # noqa: E402
from pokeagent.family.report import report_path  # noqa: E402
from pokeagent.family.seed import seed_own  # noqa: E402
from pokeagent.game import BLUE, RED, YELLOW  # noqa: E402


def mm(**kw):
    base = {"visited": {}, "warps": {}, "blocked": [], "jumps": {}, "npcs": {}}
    base.update(kw)
    return base


def doc(**maps):
    return {"maps": maps}


def merge(dst, src, edits=None):
    swarm_merge.merge_memory(dst, src, edits=edits)


def test_family_active_rules(tmp_path):
    shared = tmp_path / "maps.json"
    assert not family_active(RED, shared)            # Red-only repo: inactive
    assert family_active(BLUE, shared)               # a family sibling: active
    assert not family_active(YELLOW, shared)         # own family: never
    pv.save(shared, {"version": 1, "facts": {}})
    assert family_active(RED, shared)                # Red once provenance exists


def test_red_only_merge_creates_no_family_files(tmp_path):
    shared, own = tmp_path / "maps.json", tmp_path / "own.json"
    own.write_text(json.dumps(doc(**{"1": mm(visited={"1,1": 1})})))
    swarm_merge.merge_file_into(shared, own)  # POKEAGENT_GAME unset -> Red
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "own.json") == ["maps.json"]


def test_provenance_rules(tmp_path):
    shared = tmp_path / "maps.json"
    dst = doc(**{"1": mm(visited={"1,1": 1})})
    fold_agent_memory(shared, dst, doc(**{"1": mm(visited={"1,1": 2, "2,2": 1})}), BLUE, merge)
    p = pv.load(shared)
    assert p["facts"]["1/visited/1,1"] == ["pokemon-red", "pokemon-blue"]
    assert p["facts"]["1/visited/2,2"] == ["pokemon-blue"]
    assert pv.observers(p, "9/visited/0,0") == ["pokemon-red"]  # unrecorded = Red's


def test_disagreements_go_to_overlay_and_shared_stays(tmp_path):
    shared = tmp_path / "maps.json"
    npc = lambda last, moves=False: {"pic": 1, "slot": 0, "positions": {"%d,%d" % tuple(last): 1}, "moves": moves, "last": last}  # noqa: E731
    dst = doc(**{"1": mm(warps={"3,3,DOWN": [2, 1, 1]}, jumps={"5,5,DOWN": [5, 7]},
                         npcs={"a": npc([1, 1]), "m": npc([1, 1], True)}, visited={"1,1": 1})})
    agent = doc(**{"1": mm(warps={"3,3,DOWN": [9, 9, 9]}, jumps={"5,5,DOWN": [5, 8]},
                           npcs={"a": npc([4, 4]), "m": npc([4, 4], True)}, visited={"1,1": 50})})
    res = fold_agent_memory(shared, dst, agent, BLUE, merge)
    assert dst["maps"]["1"]["warps"]["3,3,DOWN"] == [2, 1, 1]       # shared value stays
    assert dst["maps"]["1"]["jumps"]["5,5,DOWN"] == [5, 7]
    assert dst["maps"]["1"]["npcs"]["a"]["last"] == [1, 1]
    o = load_overlay(shared, BLUE.key)["maps"]["1"]
    assert o["warps"]["3,3,DOWN"] == [9, 9, 9] and o["jumps"]["5,5,DOWN"] == [5, 8] and o["npcs"]["a"]["last"] == [4, 4]
    assert "m" not in o["npcs"]                                   # a moving NPC is not a disagreement
    assert dst["maps"]["1"]["visited"]["1,1"] == 50               # counts keep max-merge
    lines = report_path(shared).read_text().splitlines()
    assert res["reported"] == 3 and len(lines) == 3
    snap = copy.deepcopy(dst)
    fold_agent_memory(shared, dst, agent, BLUE, merge)           # idempotent: no duplicate report line
    assert len(report_path(shared).read_text().splitlines()) == 3 and dst == snap


def test_overlay_keeps_exclusives_separate_per_game(tmp_path):
    shared = tmp_path / "maps.json"
    dst = doc(**{"1": mm(warps={"3,3,DOWN": [2, 1, 1]})})
    fold_agent_memory(shared, dst, doc(**{"1": mm(warps={"3,3,DOWN": [9, 9, 9]})}), BLUE, merge)
    assert not overlay_path(shared, "pokemon-red").exists()      # Red sees the shared value only
    eff_blue = effective_memory(dst, load_overlay(shared, BLUE.key))
    eff_red = effective_memory(dst, load_overlay(shared, RED.key))
    assert eff_blue["maps"]["1"]["warps"]["3,3,DOWN"] == [9, 9, 9]
    assert eff_red["maps"]["1"]["warps"]["3,3,DOWN"] == [2, 1, 1]


def test_wall_rules():
    jumps = {"5,26,DOWN": [5, 28]}
    shared = mm(jumps=jumps, blocked=["5,28,UP", "9,28,UP", "1,1,UP", "3,3,UP", "7,7,UP"])
    agent = mm(visited={"1,1": 1, "1,0": 1, "3,3": 1}, paths={})
    assert {d["kind"] for d in find_disagreements(shared, agent, BLUE, "1")} == {"wall_suspect"}
    kinds = {d["key"]: d["kind"] for d in find_disagreements(shared, agent, BLUE, "1")}
    assert kinds == {"1,1,UP": "wall_suspect"}                   # ledge_exact/row never; one end unvisited not reported
    agent["paths"] = {"3,3,UP": {"to": [3, 2]}}
    got = {d["key"]: d for d in find_disagreements(shared, agent, BLUE, "1")}
    assert got["3,3,UP"]["kind"] == "wall_open" and got["3,3,UP"]["section"] == "blocked_not"


def test_wall_open_goes_to_blocked_not_and_effective_blocked(tmp_path):
    shared = tmp_path / "maps.json"
    dst = doc(**{"1": mm(blocked=["3,3,UP"])})
    agent = doc(**{"1": mm(paths={"3,3,UP": {"to": [3, 2]}})})
    fold_agent_memory(shared, dst, agent, BLUE, merge)
    assert dst["maps"]["1"]["blocked"] == ["3,3,UP"]            # the shared wall stays (Red still has it)
    assert effective_memory(dst, load_overlay(shared, BLUE.key))["maps"]["1"]["blocked"] == []


def test_effective_memory_without_overlay_is_equal():
    d = doc(**{"1": mm(warps={"a": [1]}, blocked=["1,1,UP"])})
    for o in (None, {}, {"maps": {}}):
        assert json.dumps(effective_memory(d, o), sort_keys=True) == json.dumps(d, sort_keys=True)


def test_both_ways_blue_then_red_then_twice(tmp_path):
    shared = tmp_path / "maps.json"
    dst = doc(**{"1": mm(visited={"0,0": 1})})
    fold_agent_memory(shared, dst, doc(**{"1": mm(visited={"1,1": 1})}), BLUE, merge)
    fold_agent_memory(shared, dst, doc(**{"1": mm(visited={"2,2": 1})}), RED, merge)
    assert set(dst["maps"]["1"]["visited"]) == {"0,0", "1,1", "2,2"}   # a Red-only fact survives the Blue fold
    p = pv.load(shared)["facts"]
    assert p["1/visited/1,1"] == ["pokemon-blue"] and p["1/visited/2,2"] == ["pokemon-red"]
    snap, psnap = copy.deepcopy(dst), copy.deepcopy(p)
    fold_agent_memory(shared, dst, doc(**{"1": mm(visited={"1,1": 1})}), BLUE, merge)
    assert dst == snap and pv.load(shared)["facts"] == psnap


def test_merge_file_into_uses_the_running_game(tmp_path, monkeypatch):
    monkeypatch.setenv("POKEAGENT_GAME", "pokemon-blue")
    shared, own = tmp_path / "maps.json", tmp_path / "own.json"
    own.write_text(json.dumps(doc(**{"1": mm(visited={"1,1": 1})})))
    swarm_merge.merge_file_into(shared, own)
    assert pv.provenance_path(shared).exists()
    assert pv.load(shared)["facts"]["1/visited/1,1"] == ["pokemon-blue"]


def test_seed_own_overlay_first_for_blue_plain_copy_for_red(tmp_path):
    shared = tmp_path / "maps.json"
    dst = doc(**{"1": mm(warps={"3,3,DOWN": [2, 1, 1]})})
    shared.write_text(json.dumps(dst))
    fold_agent_memory(shared, dst, doc(**{"1": mm(warps={"3,3,DOWN": [9, 9, 9]})}), BLUE, merge)
    shared.write_text(json.dumps(dst))
    own = tmp_path / "own.json"
    seed_own(shared, own, BLUE)
    assert json.loads(own.read_text())["maps"]["1"]["warps"]["3,3,DOWN"] == [9, 9, 9]
    seed_own(shared, own, RED)
    assert own.read_bytes() == shared.read_bytes()


def test_kb_overlay_round_trip_and_base_untouched(tmp_path):
    base = {"wild": {"1": [1], "2": [2]}, "other": 5, "same": {"a": 1}}
    game = {"wild": {"1": [1], "2": [9]}, "other": 6, "same": {"a": 1}}
    assert kb_overlay.build_overlay(base, game) == {"wild": {"2": [9]}, "other": 6}
    assert kb_overlay.read(base, kb_overlay.build_overlay(base, game)) == game
    bp = tmp_path / "kb" / "rom_tables.json"
    bp.parent.mkdir()
    bp.write_text(json.dumps(base))
    before = bp.read_bytes()
    kb_overlay.write_overlay(bp, "pokemon-blue", base, game)
    assert bp.read_bytes() == before
    d = bp.parent / "overlay" / "pokemon-blue"
    assert json.loads((d / "disagreements.json").read_text()) == {"other": 1, "wild": 1}


def test_seed_own_is_byte_copy_when_no_overlay(tmp_path):
    shared, own = tmp_path / "maps.json", tmp_path / "own.json"
    shared.write_bytes(b'{ "maps":   {"1": {}} }\n')  # odd formatting: json.dumps would rewrite it
    seed_own(shared, own, BLUE)
    assert own.read_bytes() == shared.read_bytes()
