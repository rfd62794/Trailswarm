"""statelib.cells: library entries -> one goexplore cell per (name|build), clean verdicts only, tries file."""
import json

from pokeagent import statefp
from pokeagent.statelib import cells


def ent(name="to_route2", tier="checkpoint", build="A", verdict="clean",
        state="runs/checkpoints/x.state", segment="to_pewter",
        steps=100, faints=0, readiness=0.5, parent="to_route1.state", **kw):
    e = {"tier": tier, "name": name, "segment": segment, "state": state, "build": build,
         "verdict": verdict, "parent": parent,
         "metrics": {"steps": steps, "faints": faints, "readiness": readiness, "readiness_boss": "brock"}}
    e.update(kw)
    return e


def test_cell_id_and_clean_only():
    assert cells.cell_id(ent(build=None)) == "to_route2|unknown"
    assert cells.cell_id(ent(tier="leg", name="14_5_3", segment="to_route3")) == "leg:to_route3|A"
    assert cells.is_cell(ent(verdict="clean"))
    assert not cells.is_cell(ent(verdict="violation"))
    assert not cells.is_cell(ent(verdict="unknown"))
    assert cells.is_cell(ent(verdict="unknown"), allow_unknown=True)


def test_to_archive_one_cell_per_build_clean_only():
    es = [ent(build="A"), ent(build="B"), ent(build="V", verdict="violation")]
    a = cells.to_archive(es, {"to_route2": 4}, tries={})
    assert sorted(a.entries) == ["to_route2|A", "to_route2|B"]
    assert all(e.goals == 4 for e in a.entries.values())
    a2 = cells.to_archive(es, {"to_route2": 4}, tries={}, allow_unknown=True)
    assert "to_route2|V" not in a2.entries                        # a violation never becomes a cell


def test_to_archive_keeps_the_better_state_per_cell():
    slow, fast = ent(state="a.state", steps=900), ent(state="b.state", steps=100)
    a = cells.to_archive([slow, fast], {"to_route2": 4}, tries={})
    e = a.entries["to_route2|A"]
    assert (e.state, e.steps, e.parent) == ("b.state", 100, "to_route1.state")
    a2 = cells.to_archive([fast, slow], {"to_route2": 4}, tries={})     # entry order cannot matter
    assert a2.entries["to_route2|A"].state == "b.state"


def test_null_steps_rank_as_the_slowest_and_tries_become_n_seen():
    a = cells.to_archive([ent(steps=None)], {"to_route2": 4},
                         tries={"to_route2|A": {"tries": 5, "solves": 2}})
    e = a.entries["to_route2|A"]
    assert e.steps == cells.NO_STEPS and e.n_seen == 5


def test_goals_index_leg_takes_the_segments_start():
    gi = {g: i for i, g in enumerate(["to_pewter", "to_gym", "beat_brock", "to_route3"])}
    leg = ent(tier="leg", name="14_5_3", segment="to_route3")
    a = cells.to_archive([leg], gi, tries={})
    assert a.entries["leg:to_route3|A"].goals == gi["beat_brock"]       # to_route3's start checkpoint
    piece = ent(tier="leg", name="14_5_3.1", segment="to_route3@3c")
    a2 = cells.to_archive([piece], gi, tries={})
    assert a2.entries["leg:to_route3@3c|A"].goals == gi["beat_brock"]


def test_hp_comes_from_the_fingerprint_sidecar(tmp_path):
    p = tmp_path / "s.state"
    p.write_bytes(b"x")
    statefp.write(p, {"v": 1, "party": [[1, 5, 5, 10], [2, 7, 7, 7]]})
    a = cells.to_archive([ent(state=str(p))], {"to_route2": 4}, tries={})
    assert a.entries["to_route2|A"].hp == (5 + 7) / (10 + 7)
    a2 = cells.to_archive([ent(state="nope.state")], {"to_route2": 4}, tries={})
    assert a2.entries["to_route2|A"].hp == 0.0


def test_record_try_accumulates_atomically(tmp_path):
    cells.record_try(tmp_path, "to_route2|A", True)
    cells.record_try(tmp_path, "to_route2|A", False)
    cells.record_try(tmp_path, "to_route2|B", True)
    t = cells.read_tries(tmp_path)
    assert t["to_route2|A"]["tries"] == 2 and t["to_route2|A"]["solves"] == 1 and t["to_route2|A"]["last"]
    assert t["to_route2|B"]["tries"] == 1
    assert json.loads((tmp_path / cells.TRIES).read_text())["v"] == 1
    assert cells.read_tries(tmp_path / "none") == {}
