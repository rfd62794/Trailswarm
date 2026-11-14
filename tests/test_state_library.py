"""runs/states/library.json: checkpoints and legs indexed by team build, segment and verdict; retention keeps the
best-K legs per (segment, build) and never drops a checkpoint."""
import json
import os
from pathlib import Path

from pokeagent import statefp
from pokeagent.statelib import library

HARDEN, TACKLE, EMBER = 106, 33, 1
KAKUNA, CHARMANDER, PIDGEY = 113, 176, 36
KB = {"name_of_internal": {"36": "PIDGEY", "113": "KAKUNA", "176": "CHARMANDER", "178": "CHARMELEON"},
      "moves": {"1": {"name": "EMBER", "power": 40}, "33": {"name": "TACKLE", "power": 35},
                "40": {"name": "POISON STING", "power": 15}, "106": {"name": "HARDEN", "power": 0}}}


def member(species, level, moves=()):
    return {"species": species, "level": level, "moves": list(moves), "hp": 10, "max_hp": 10, "ot_id": 1, "exp": 1}


def state(d, name, fp, mtime=1000.0):
    p = d / name
    p.write_bytes(b"x")
    statefp.write(p, fp)
    os.utime(p, (mtime, mtime))
    return p


def test_build_indexes_checkpoint_and_leg_entries(tmp_path):
    cps, legs = tmp_path / "checkpoints", tmp_path / "states"
    cps.mkdir(), legs.mkdir()
    (tmp_path / "runs/explore-x").mkdir(parents=True)
    (tmp_path / "runs/explore-x/meta.json").write_text(json.dumps({"seed": 42}))
    clean_team = [member(CHARMANDER, 9, (EMBER,)), member(PIDGEY, 5, (TACKLE,))]
    state(cps, "to_route2.state",
          {"v": 1, "map": 13, "frames": 1000, "source_run": "explore-x", "team": clean_team})
    state(cps, "to_pewter.state",
          {"v": 1, "map": 2, "parent": "to_route2.state", "team": [member(KAKUNA, 7, (HARDEN,))]})
    state(legs, "14_5_3.state",
          {"v": 1, "map": 14, "frames": 200, "team": clean_team}, mtime=2000)
    state(legs, "99_1_1.state", {"v": 1, "map": 99, "team": [member(PIDGEY, 5, (TACKLE,))]})
    doc, dropped = library.build([cps, legs], root=tmp_path, out=tmp_path / "lib.json", kb=KB)
    assert doc["v"] == 1 and len(doc["entries"]) == 4 and (tmp_path / "lib.json").exists()
    by_name = {e["name"]: e for e in doc["entries"]}
    route2 = by_name["to_route2"]
    assert (route2["tier"], route2["segment"], route2["build"], route2["verdict"]) == \
        ("checkpoint", "to_pewter", "CHARMANDER:L5|PIDGEY:L5", "clean")
    assert route2["metrics"]["steps"] == 1000 and route2["run"] == "explore-x" and route2["seed"] == 42
    assert route2["team"] == [[176, 9, ["EMBER"]], [36, 5, ["TACKLE"]]]
    assert route2["state"].endswith("checkpoints/to_route2.state")
    pewter = by_name["to_pewter"]
    assert pewter["segment"] == "to_gym" and pewter["verdict"] == "violation"
    assert pewter["parent"] == "to_route2.state" and "wild KAKUNA" in pewter["violations"][0]
    leg = by_name["14_5_3"]
    assert leg["tier"] == "leg" and leg["segment"] == "to_route3"            # map 14 is to_route3's detector map
    assert by_name["99_1_1"]["segment"] is None                             # map 99 is in no segment's range
    assert dropped == []                                                    # under K legs per (segment, build)


def test_seed_and_faints_come_from_the_run_dir(tmp_path):
    run = tmp_path / "runs" / "r7"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"seed": 42}))
    (run / "battles.jsonl").write_text(json.dumps({
        "party_before": [[1, 5, 0, 20, 20], [2, 5, 0, 10, 10]],
        "party_after": [[1, 5, 0, 0, 20], [2, 5, 0, 10, 10]]}) + "\n")
    cps = tmp_path / "cps"
    cps.mkdir()
    state(cps, "x.state", {"v": 1, "map": 1, "source_run": "r7", "team": [member(PIDGEY, 5, (TACKLE,))]})
    state(cps, "y.state", {"v": 1, "map": 1, "team": [member(PIDGEY, 5, (TACKLE,))]})
    doc, _ = library.build([cps], root=tmp_path, out=tmp_path / "lib.json", kb=KB)
    by_name = {e["name"]: e for e in doc["entries"]}
    assert by_name["x"]["seed"] == 42 and by_name["x"]["metrics"]["faints"] == 1
    assert by_name["x"]["metrics"]["steps"] is None                         # no frames stamped: null, not guessed
    assert by_name["y"]["run"] is None and by_name["y"]["seed"] is None and by_name["y"]["metrics"]["faints"] is None


def test_retain_keeps_best_k_legs_never_a_checkpoint():
    def leg(name, verdict="clean", readiness=0.5, steps=100, created="2026-01-01T00:00:00+00:00"):
        return {"tier": "leg", "name": name, "segment": "to_route3", "build": "B", "verdict": verdict,
                "created": created,
                "metrics": {"steps": steps, "faints": None, "readiness": readiness, "readiness_boss": "brock"}}
    a = leg("a", readiness=0.9, steps=10)
    b = leg("b", readiness=0.8)
    c = leg("c", readiness=0.7)
    d = leg("d", verdict="violation", readiness=0.99)                        # readiness cannot save a violator
    e = leg("e", verdict="unknown", readiness=0.95, created="2026-01-02T00:00:00+00:00")
    other_build = leg("f", steps=1) | {"build": "OTHER"}
    ck = {"tier": "checkpoint", "name": "x.state", "segment": "to_route3", "build": "B", "verdict": "clean",
          "created": "2025-12-01T00:00:00+00:00", "metrics": {}}
    kept, dropped = library.retain([a, b, c, d, e, other_build, ck], k=3)
    assert {x["name"] for x in kept} == {"a", "b", "c", "f", "x.state"}      # B keeps its best 3 legs + others + ck
    assert {x["name"] for x in dropped} == {"d", "e"}
    kept2, dropped2 = library.retain([d, e], k=3)
    assert dropped2 == []                                                    # groups under K drop nothing


def test_read_returns_an_empty_index_for_a_missing_library(tmp_path):
    assert library.read(tmp_path / "nope.json")["entries"] == []
