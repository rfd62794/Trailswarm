"""brain compare: classify_wall ledge split and compare_memory counts over shared maps."""
import io
import json
from contextlib import redirect_stdout

import pytest

import pokeagent.brain as brain
from pokeagent.brain.ledges import classify_wall, opposite, parse_edge
from pokeagent.cli_brain import main as brain_main


# --- ledges.py ---

def test_opposite_and_parse_edge():
    assert opposite("UP") == "DOWN" and opposite("DOWN") == "UP"
    assert opposite("LEFT") == "RIGHT" and opposite("RIGHT") == "LEFT"
    assert parse_edge("5,28,UP") == (5, 28, "UP")
    for bad in ("bad-edge", "5,28", "5,28,UP,X", "x,28,UP", "5,28,JUMP"):
        with pytest.raises(ValueError):
            parse_edge(bad)


def test_classify_wall_exact_row_plain():
    m = {"jumps": {"5,26,DOWN": [5, 28]}}  # learn() writes the back-edge "5,28,UP" into blocked
    assert classify_wall(m, "5,28,UP") == "ledge_exact"      # the recorded jump's own back-edge
    assert classify_wall(m, "9,28,UP") == "ledge_row"        # same row as the landing, same direction
    assert classify_wall(m, "9,29,UP") == "plain"            # right direction, wrong row
    assert classify_wall(m, "5,28,DOWN") == "plain"          # wrong direction (jump was DOWN)
    assert classify_wall(m, "4,4,LEFT") == "plain"           # unrelated wall
    assert classify_wall(m, "bad-edge") == "plain"           # malformed edges classify as plain
    m2 = {"jumps": {"6,6,RIGHT": [8, 6]}}                     # horizontal jump: column rule
    assert classify_wall(m2, "8,6,LEFT") == "ledge_exact"
    assert classify_wall(m2, "8,9,LEFT") == "ledge_row"
    assert classify_wall(m2, "7,9,LEFT") == "plain"


# --- compare_memory ---

def _baseline():
    return {"maps": {
        "1": {"visited": {"5,28": 1, "5,26": 3, "3,4": 2, "5,5": 1},
              "blocked": ["5,28,UP", "9,28,UP", "1,1,DOWN", "bad-edge"],
              "jumps": {"5,26,DOWN": [5, 28]},
              "warps": {"3,5,DOWN": [2, 0, 0], "7,7,UP": [3, 1, 1]},
              "npcs": {"s1": {"pic": 9, "last": [4, 4], "moves": False},
                       "s2": {"pic": 5, "last": [8, 8], "moves": True}}},
        "2": {"visited": {"0,0": 1}, "blocked": [], "warps": {}},
        "3": {"visited": {"9,9": 1}},  # baseline only: never compared
    }}


def _candidate():
    return {"maps": {
        "1": {"visited": {"5,28": 1, "5,27": 1, "9,28": 1, "9,27": 1, "1,1": 1, "1,2": 1,
                          "4,4": 1, "3,4": 1, "0,9": 1},
              "warps": {"3,5,DOWN": [2, 0, 0], "7,7,UP": [4, 1, 1], "2,2,LEFT": [9, 9, 9]},
              "npcs": {"s1": {"pic": 9, "last": [4, 4], "moves": False},
                       "s3": {"pic": 2, "last": [1, 2], "moves": False},
                       "s4": {"pic": 7, "last": [6, 6], "moves": True}}},
        "2": {"visited": {"0,0": 1, "1,1": 1}, "blocked": ["0,0,UP"], "warps": {"0,0,DOWN": [1, 2, 3]}},
        "4": {"visited": {"8,8": 1}},  # candidate only: never compared
    }}


def test_compare_memory_totals_and_shape():
    out = brain.compare_memory(_baseline(), _candidate())
    assert out["shared_maps"] == 2
    t = out["totals"]
    assert set(t) == {"tiles", "warps", "npcs", "walls"}
    assert set(t["tiles"]) == {"candidate", "overlap", "candidate_only"}
    assert set(t["warps"]) == {"common", "different", "candidate_only"}
    assert set(t["npcs"]) == {"candidate", "overlap"}
    assert set(t["walls"]) == {"baseline_walls", "suspect", "ledge_exact", "ledge_row",
                               "plain", "unexplained", "malformed"}
    # map 1: candidate visited both ends of 3 of the 4 baseline edges (bad-edge cannot parse)
    assert t["tiles"] == {"candidate": 11, "overlap": 3, "candidate_only": 8}
    assert t["warps"] == {"common": 2, "different": 1, "candidate_only": 2}
    assert t["npcs"] == {"candidate": 2, "overlap": 1}
    assert t["walls"] == {"baseline_walls": 4, "suspect": 3, "ledge_exact": 1,
                          "ledge_row": 1, "plain": 2, "unexplained": 2, "malformed": 1}


def test_compare_memory_rows_and_shared_only():
    out = brain.compare_memory(_baseline(), _candidate())
    assert len(out["rows"]) == 2
    r1, r2 = out["rows"]
    assert r1["map"] == 1  # worst by unexplained first
    assert set(r1) == {"map", "tiles", "warps", "npcs", "walls"}
    assert r1["walls"]["suspect"] == 3 and r1["walls"]["ledge_exact"] == 1
    assert r1["walls"]["ledge_row"] == 1 and r1["walls"]["unexplained"] == 2
    assert r1["tiles"] == {"candidate": 9, "overlap": 2, "candidate_only": 7}
    assert r2["map"] == 2
    # map 3 (baseline only) and map 4 (candidate only) never contribute
    assert all(r["map"] not in (3, "3", 4, "4") for r in out["rows"])


def test_compare_memory_empty_input():
    out = brain.compare_memory({}, {"maps": {"1": {}}})
    assert out["shared_maps"] == 0 and out["rows"] == []
    assert out["totals"]["tiles"]["candidate"] == 0 and out["totals"]["walls"]["baseline_walls"] == 0


# --- CLI ---

def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = brain_main(argv)
    return rc, buf.getvalue()


def test_cli_compare(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_baseline()), encoding="utf-8")
    b.write_text(json.dumps(_candidate()), encoding="utf-8")
    rc, out = _run(["compare", str(a), str(b)])
    assert rc == 0
    rep = json.loads(out)
    assert rep["shared_maps"] == 2 and rep["totals"]["walls"]["suspect"] == 3
    rc, out = _run(["compare", str(a), str(b), "--text"])
    assert rc == 0 and "heuristic" in out and "shared maps: 2" in out
    rc, out = _run(["compare", str(a), str(tmp_path / "missing.json")])
    assert rc == 1
