"""statelib.start_pick: exploit/alternative/promising draws over (name|build) cells, deterministic per seed."""
import json
import random

from pokeagent.statelib import start_pick


def ent(name="to_route2", build="A", verdict="clean", state=None, readiness=0.5, steps=100, faints=0):
    return {"tier": "checkpoint", "name": name, "segment": "to_pewter",
            "state": state or f"runs/checkpoints/{name}.{build}.state",
            "build": build, "verdict": verdict,
            "metrics": {"steps": steps, "faints": faints, "readiness": readiness, "readiness_boss": "b"}}


def three():
    return [ent(build="A", readiness=0.9), ent(build="B", readiness=0.5), ent(build="C", readiness=0.2)]


def test_none_when_no_clean_candidate():
    assert start_pick.pick_start([], "to_route2", random.Random(1), {}) is None
    assert start_pick.pick_start([ent(name="other")], "to_route2", random.Random(1), {}) is None
    assert start_pick.pick_start([ent(verdict="violation")], "to_route2", random.Random(1), {}) is None


def test_one_build_is_always_exploit():
    p = start_pick.pick_start([ent(), ent(state="s2.state")], "to_route2", random.Random(4), {})
    assert p.mode == "exploit" and p.build == "A" and p.cell == "to_route2|A" and p.why


def test_deterministic_for_a_seed():
    es = three()
    a = start_pick.pick_start(es, "to_route2", random.Random(9), {})
    b = start_pick.pick_start(es, "to_route2", random.Random(9), {})
    assert a == b


def test_mode_shares_within_tolerance():
    seen = {"exploit": 0, "alternative": 0, "promising": 0}
    for i in range(2000):
        p = start_pick.pick_start(three(), "to_route2", random.Random(i), {})
        seen[p.mode] += 1
    for mode, share in start_pick.SHARES.items():
        assert abs(seen[mode] / 2000 - share) < 0.05, (mode, seen)


def test_exploit_picks_best_readiness_then_steps_then_faints():
    es = [ent(build="A", readiness=0.5, steps=100, faints=0),
          ent(build="B", readiness=0.9, steps=999, faints=3),   # readiness outranks everything
          ent(build="C", readiness=0.9, steps=50, faints=1),    # tied readiness -> fewer steps
          ent(build="D", readiness=None, steps=1)]              # null readiness ranks last
    p = start_pick.pick_start(es, "to_route2", random.Random(0), {},
                            shares={"exploit": 1.0, "alternative": 0.0, "promising": 0.0})
    assert p.build == "C" and p.mode == "exploit"


def test_alternative_draws_among_non_exploit_weighted_by_rarity():
    tr = {"to_route2|B": {"tries": 50}, "to_route2|C": {"tries": 0}}
    picks = [start_pick.pick_start(three(), "to_route2", random.Random(i), tr,
                                   shares={"exploit": 0.0, "alternative": 1.0, "promising": 0.0})
             for i in range(200)]
    assert all(p.mode == "alternative" and p.build in ("B", "C") for p in picks)
    assert sum(p.build == "C" for p in picks) > sum(p.build == "B" for p in picks)   # rarely-tried wins


def test_promising_picks_under_tried_best_readiness_else_alternative():
    es = three() + [ent(build="D", readiness=None)]
    tr = {"to_route2|A": {"tries": 10}, "to_route2|B": {"tries": 10},
          "to_route2|C": {"tries": 1}, "to_route2|D": {"tries": 0}}
    p = start_pick.pick_start(es, "to_route2", random.Random(0), tr,
                              shares={"exploit": 0.0, "alternative": 0.0, "promising": 1.0})
    assert p.mode == "promising" and p.build == "C"    # the under-tried cell with the best readiness
    tr2 = {c: {"tries": 10} for c in ("to_route2|A", "to_route2|B", "to_route2|C", "to_route2|D")}
    p2 = start_pick.pick_start(es, "to_route2", random.Random(0), tr2,
                               shares={"exploit": 0.0, "alternative": 0.0, "promising": 1.0})
    assert p2.mode == "alternative" and p2.build in ("B", "C", "D")   # nothing under-tried: falls back


def test_load_shares_overrides_and_defaults(tmp_path):
    p = tmp_path / "runs"
    p.mkdir()
    (p / "curriculum_builds.json").write_text(json.dumps(
        {"shares": {"exploit": 0.1, "alternative": 0.8, "promising": 0.1}}))
    assert start_pick.load_shares(tmp_path)["alternative"] == 0.8
    (p / "curriculum_builds.json").write_text("not json")
    assert start_pick.load_shares(tmp_path) == start_pick.SHARES      # malformed file -> defaults
    (p / "curriculum_builds.json").unlink()
    assert start_pick.load_shares(tmp_path) == start_pick.SHARES      # missing file -> defaults
