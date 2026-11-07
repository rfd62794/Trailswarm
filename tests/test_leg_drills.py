"""Leg drills and grind drills: synthetic emulator and logs (no ROM): entry-state saves, the drill stop condition and budget,
the scheduler, folding into legs.json / the grind atlas, and the discovery-state refusal."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent.explorer.press_frame import PressFrame
from pokeagent.grind import refresh
from pokeagent.grind.drill import GrindDrillMonitor
from pokeagent.legs.grass import pace_button, to_grass
from pokeagent.grind.observed import DRILL_GOAL, fold, pooled
from pokeagent.legs import attach, drill as D, drill_fold, schedule, states as S
from pokeagent.legs import grid as G
from pokeagent.legs.split import Leg, drill_leg

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeEmu:
    def __init__(self, battle=0, hp=20, mx=20):
        self.mem = {0xD057: battle, 0xD16C: hp >> 8, 0xD16D: hp & 255, 0xD18D: mx >> 8, 0xD18E: mx & 255}
        self.frames, self.saves = 0, 0

    def read(self, a):
        return self.mem.get(a, 0)

    def save_state(self, path):
        self.saves += 1
        Path(path).write_bytes(b"state%d" % self.saves)


def ctx_of(emu=None, run_dir=None, step=0):
    c = SimpleNamespace(emu=emu or FakeEmu(), step=step, done=False, logs=[], run_dir=Path(run_dir or "."), opts=SimpleNamespace(starter="x"),
                        battles=0, battles_won=0)
    c.log = lambda t, tag=None: c.logs.append(t)
    return c


def fr(before, after, box=False, name="RIGHT"):
    return PressFrame(name, "agent", "", before=before, after=after, box_after=box)


# ---------------------------------------------------------------- leg entry states
def test_saver_saves_calm_entries_only(tmp_path):
    emu = FakeEmu()
    sv = S.LegStateSaver(tmp_path)
    assert sv.observe(ctx_of(emu), fr((1, 3, 3), (1, 3, 4))) is None            # same map: not an entry
    assert sv.observe(ctx_of(emu), fr((1, 3, 3), (2, 5, 6), box=True)) is None  # text box up
    assert sv.observe(ctx_of(FakeEmu(battle=1)), fr((1, 3, 3), (2, 5, 6))) is None
    assert sv.observe(ctx_of(FakeEmu(hp=10, mx=20)), fr((1, 3, 3), (2, 5, 6))) is None   # exactly half is not above half
    assert sv.observe(ctx_of(FakeEmu(hp=0, mx=0)), fr((1, 3, 3), (2, 5, 6))) is None     # no lead
    p = sv.observe(ctx_of(emu), fr((1, 3, 3), (2, 5, 6)))
    assert p == tmp_path / "2_5_6.state" and p.read_bytes() == b"state1"
    assert sv.observe(ctx_of(emu), fr((1, 3, 3), (2, 5, 6))) is None             # once per key per run


def test_saver_keeps_three_per_key_newest_first(tmp_path):
    emu = FakeEmu()
    for _ in range(5):
        S.LegStateSaver(tmp_path).observe(ctx_of(emu), fr((1, 0, 0), (2, 5, 6)))   # five runs
    assert sorted(f.name for f in tmp_path.glob("*.state")) == ["2_5_6.1.state", "2_5_6.2.state", "2_5_6.state"]
    assert (tmp_path / "2_5_6.state").read_bytes() == b"state5" and (tmp_path / "2_5_6.2.state").read_bytes() == b"state3"
    assert S.keys(tmp_path) == {(2, 5, 6)} and S.newest(tmp_path, 2, 5, 6) == tmp_path / "2_5_6.state"


def test_saver_total_cap_evicts_oldest(tmp_path):
    emu = FakeEmu()
    sv = S.LegStateSaver(tmp_path, max_files=20)
    for i in range(40):
        sv.observe(ctx_of(emu), fr((1, 0, 0), (2, i, 0)))
    n = len(list(tmp_path.glob("*.state")))
    assert n <= 20 and (tmp_path / "2_39_0.state").exists() and not (tmp_path / "2_0_0.state").exists()


def test_saver_route_filter_and_failure_never_raises(tmp_path):
    sv = S.LegStateSaver(tmp_path, route={2})
    assert sv.observe(ctx_of(), fr((1, 0, 0), (9, 1, 1))) is None and not list(tmp_path.glob("*.state"))   # map 9 is off the route
    assert sv.observe(ctx_of(), fr((1, 0, 0), (2, 1, 1))) is not None
    bad = FakeEmu()
    bad.save_state = lambda p: (_ for _ in ()).throw(OSError("disk full"))
    c = ctx_of(bad)
    assert S.LegStateSaver(tmp_path).observe(c, fr((1, 0, 0), (2, 7, 7))) is None and "leg state skipped" in c.logs[0]


def test_route_maps_from_segments_json(tmp_path):
    (tmp_path / "segments.json").write_text(json.dumps({"stats": {"to_route1": {"attempts": [{"maps": [0, 12]}]}, "x": {"attempts": [{"maps": [1]}]}}}))
    assert S.route_maps(tmp_path) == {0, 1, 12} and S.route_maps(tmp_path / "nope") == set()


# ---------------------------------------------------------------- drill stop condition and budget
def test_parse_and_budget():
    sp = D.parse("12:5,6->12,12:UP")
    assert (sp.map, sp.entry, sp.exit, sp.button) == (12, (5, 6), (12, 12), "UP") and sp.text == "12:5,6->12,12:UP"
    assert sp.key_prefix == "12:5,6>12,12:" and D.parse("3:1,2->3,4").button == ""
    with pytest.raises(ValueError):
        D.parse("12:5,6>12,12")
    assert D.budget_steps(224) == 64      # ceil(3 * 224 / 10.5)
    assert D.budget_steps(16) == D.MIN_STEPS


def monitor(tmp_path, max_steps=10, par=64.0):
    return D.DrillMonitor(D.parse("5:2,2->4,2"), par, max_steps, tmp_path, tmp_path / "drills.jsonl", now=lambda: 1.0)


def test_drill_solves_on_reaching_the_exit_tile(tmp_path):
    m, c = monitor(tmp_path), ctx_of(run_dir=tmp_path)
    for step, (a, b) in enumerate([((5, 2, 2), (5, 3, 2)), ((5, 3, 2), (5, 4, 2))], 1):
        c.step = step
        ended = m.observe(c, fr(a, b))
    r = m.result
    assert ended and c.done and r["solved"] and r["reason"] == "reached_exit" and r["steps"] == 2 and r["presses"] == 2
    assert r["model_frames"] == 3 * G.FRAME_WALK and r["efficiency"] == pytest.approx(64 / 48)   # 2 tiles + the leaving press priced
    assert json.loads((tmp_path / "meta.json").read_text())["drill_result"]["solved"] is True
    assert json.loads((tmp_path / "drills.jsonl").read_text())["run"] == tmp_path.name


def test_drill_ends_on_map_change_and_counts_the_leaving_press(tmp_path):
    m, c = monitor(tmp_path), ctx_of(run_dir=tmp_path, step=1)
    assert m.observe(c, fr((5, 3, 2), (5, 3, 2))) is False                   # idle press, still in the leg
    c.step = 2
    assert m.observe(c, fr((5, 4, 2), (7, 1, 1), name="DOWN")) and m.result["solved"] and m.result["reason"] == "left_by_exit"
    assert m.result["button"] == "DOWN"
    m2, c2 = monitor(tmp_path), ctx_of(run_dir=tmp_path, step=1)
    assert m2.observe(c2, fr((5, 2, 3), (7, 1, 1))) and not m2.result["solved"] and m2.result["reason"] == "left_map"


def test_drill_budget_stops_the_run(tmp_path):
    m, c = monitor(tmp_path, max_steps=3), ctx_of(run_dir=tmp_path)
    for step in (1, 2, 3):
        c.step = step
        ended = m.observe(c, fr((5, 2, 2), (5, 2, 2), name="A"))
    assert ended and m.result["reason"] == "budget" and not m.result["solved"] and m.result["efficiency"] is None


def test_exit_equal_entry_needs_the_leaving_press(tmp_path):
    m = D.DrillMonitor(D.parse("35:10,35->10,35"), 16.0, 30, tmp_path, None)
    c = ctx_of(run_dir=tmp_path, step=1)
    assert m.observe(c, fr((35, 10, 35), (35, 10, 35), name="B")) is False    # standing on the exit tile is not enough
    c.step = 2
    assert m.observe(c, fr((35, 10, 35), (36, 3, 3), name="DOWN")) and m.result["solved"]


# ---------------------------------------------------------------- scheduler and folding
def leg_rec(key="5:2,2>4,2:RIGHT", n=5, par=64.0, med=500.0, best=300.0):
    m, rest = key.split(":", 1)
    e, rest = rest.split(">", 1)
    x, b = rest.split(":")
    return {"key": key, "map": int(m), "entry": [int(v) for v in e.split(",")], "exit": [int(v) for v in x.split(",")], "button": b,
            "samples": n, "par_frames": par, "median_frames": med, "best_frames": best, "efficiency": par / best}


def drill_res(solved=True, eff=1.0, t=1000.0, mf=64.0, leg="5:2,2->4,2", **kw):
    sp = D.parse(leg)
    return {"kind": "leg", "source": "drill", "leg": leg, "map": sp.map, "entry": list(sp.entry), "exit": list(sp.exit), "button": "",
            "solved": solved, "efficiency": eff if solved else None, "model_frames": mf, "par_frames": 64.0, "steps": 5, "presses": 5,
            "run": "r", "t": t, **kw}


def test_rank_picks_worst_waste_with_states_and_enough_samples():
    legs = {r["key"]: r for r in (leg_rec("5:2,2>4,2:RIGHT", n=5, med=500),             # waste 5 * 436
                                  leg_rec("6:1,1>2,2:UP", n=10, med=250),                 # waste 10 * 186: smaller
                                  leg_rec("7:1,1>2,2:UP", n=50, med=1000),                # biggest but no entry state
                                  leg_rec("8:1,1>2,2:UP", n=2, med=9000),                 # too few samples
                                  leg_rec("9:1,1>2,2:UP", n=9, med=64))}                  # no waste
    got = schedule.rank(legs, {(5, 2, 2), (6, 1, 1), (8, 1, 1), (9, 1, 1)}, [], 1e6)
    assert [r["key"] for r in got] == ["5:2,2>4,2:RIGHT", "6:1,1>2,2:UP"]


def test_leg_that_hit_par_twice_is_retired_for_a_while():
    legs = {r["key"]: r for r in (leg_rec("5:2,2>4,2:RIGHT"), leg_rec("6:1,1>2,2:UP", med=300))}
    st = {(5, 2, 2), (6, 1, 1)}
    one = [drill_res(eff=1.0, t=100.0)]
    assert [r["map"] for r in schedule.rank(legs, st, one, 200.0)] == [5, 6]                       # one hit: still drilled
    two = one + [drill_res(eff=0.95, t=150.0), drill_res(solved=False, t=160.0)]                  # a failure is not a hit
    assert [r["map"] for r in schedule.rank(legs, st, two, 200.0)] == [6]                          # two hits: retired
    assert [r["map"] for r in schedule.rank(legs, st, two, 150.0 + schedule.RETIRE_S + 1)] == [5, 6]   # ...for a while
    slow = [drill_res(eff=0.5, t=1.0), drill_res(eff=0.6, t=2.0)]
    assert [r["map"] for r in schedule.rank(legs, st, slow, 10.0)] == [5, 6]                      # solved but off par: keep drilling


def test_pick_builds_a_launch_config(tmp_path):
    (tmp_path / "runs" / "legs" / "states").mkdir(parents=True)
    (tmp_path / "runs" / "legs.json").write_text(json.dumps({"legs": {"5:2,2>4,2:RIGHT": leg_rec()}}))
    assert schedule.pick(tmp_path) is None                                                         # no entry state yet
    (tmp_path / "runs" / "legs" / "states" / "5_2_2.state").write_bytes(b"x")
    d = schedule.pick(tmp_path)
    assert d["leg"] == "5:2,2->4,2:RIGHT" and d["state"].endswith("5_2_2.state") and d["steps"] == D.budget_steps(64.0)


def test_drill_samples_fold_into_the_leg_record_marked_drill():
    rec = {**leg_rec(n=3, med=500, best=300), "frames_run": [300.0, 500.0, 700.0]}
    out = drill_fold.merge_drills(rec, [drill_res(mf=80.0, eff=0.8), drill_res(solved=False, mf=40.0, leg="6:1,1->2,2")])
    assert out["samples"] == 4 and out["samples_run"] == 3 and out["best_frames"] == 80.0 and out["efficiency"] == pytest.approx(0.8)
    assert out["efficiency_run"] == pytest.approx(64 / 300) and out["median_frames"] == 400.0
    assert out["drill_n"] == 1 and out["drill_solved"] == 1 and out["drills"][0]["source"] == "drill"
    failed = drill_fold.merge_drills(rec, [drill_res(solved=False, mf=40.0)])
    assert failed["best_frames"] == 300.0 and failed["samples"] == 4      # a failure costs at least 3 x par: it never beats natural runs
    assert drill_leg(drill_res(solved=False, mf=40.0)).frames == 3 * 64.0 and drill_leg(drill_res()).source == "drill"
    assert Leg("r", 1, (0, 0), (1, 1), "UP", None, 0).source == "run"
    assert drill_fold.merge_drills(rec, [drill_res(mf=80.0)]) == drill_fold.merge_drills(drill_fold.merge_drills(rec, [drill_res(mf=80.0)]), [drill_res(mf=80.0)])


def test_fold_file_rewrites_legs_json_from_the_drill_log(tmp_path):
    rec = {**leg_rec(), "samples": 5}
    (tmp_path / "legs.json").write_text(json.dumps({"legs": {rec["key"]: rec}}))
    (tmp_path / "drills.jsonl").write_text(json.dumps(drill_res(mf=70.0, eff=0.9)) + "\n{torn")
    assert drill_fold.fold_file(tmp_path / "legs.json", tmp_path / "drills.jsonl") == 1
    got = json.loads((tmp_path / "legs.json").read_text())["legs"][rec["key"]]
    assert got["samples"] == 6 and got["best_frames"] == 70.0 and got["drill_n"] == 1


def test_leg_report_score_folds_drills():
    lr = _load("leg_report")
    g = G.from_ascii(["......"])
    leg = Leg("run1", 5, (0, 0), (4, 0), "RIGHT", (6, 0, 0), 0, 9, ["RIGHT"] * 5, 5, 100.0, True)
    rows = lr.score(lambda m: g, {leg.key: [leg]}, [drill_res(leg="5:0,0->4,0", mf=90.0, eff=0.9)])
    assert rows[0]["drill_n"] == 1 and rows[0]["samples"] == 2 and rows[0]["samples_run"] == 1 and rows[0]["best_frames"] == 90.0


# ---------------------------------------------------------------- discovery states and the plan
def test_discovery_states_are_never_drill_starts(tmp_path):
    from pokeagent.novelty.discoveries import DIR_NAME
    sd = tmp_path / "runs" / DIR_NAME / "states"
    sd.mkdir(parents=True)
    (sd / "5_2_2.state").write_bytes(b"x")
    with pytest.raises(SystemExit, match="discovery"):
        attach.plan("5:2,2->4,2", None, 600, sd, None)
    with pytest.raises(SystemExit, match="discovery"):
        attach.plan(None, 5, 600, sd, None)
    with pytest.raises(SystemExit, match="discovery"):
        attach.plan("5:2,2->4,2", None, 600, tmp_path, None, explicit_state=sd / "5_2_2.state")
    c = ctx_of(run_dir=tmp_path)
    c.leg_saver = None
    attach.attach(c, None, True, tmp_path / "out", start_state=sd / "x.state")      # a run that began in a discovery state saves nothing
    assert c.leg_saver is None
    attach.attach(c, None, True, tmp_path / "out", start_state=tmp_path / "ok.state", runs_dir=tmp_path)
    assert isinstance(c.leg_saver, S.LegStateSaver)


def test_plan_needs_a_saved_state(tmp_path):
    with pytest.raises(SystemExit, match="no entry state"):
        attach.plan("5:2,2->4,2", None, 600, tmp_path, None)
    assert attach.plan(None, None, 600, tmp_path, None) is None


# ---------------------------------------------------------------- grind drill
def test_pace_and_walk_to_grass():
    g = G.from_ascii(["..gg.", "....."])
    assert pace_button(g, (2, 0), "RIGHT") == ("RIGHT", "RIGHT")
    assert pace_button(g, (3, 0), "RIGHT") == ("LEFT", "LEFT")                  # next tile is not grass: turn round
    assert to_grass(g, (0, 1)) == ["RIGHT", "RIGHT", "UP"] or to_grass(g, (0, 1))[-1] in ("UP", "RIGHT")
    assert to_grass(G.from_ascii(["...."]), (0, 0)) == []


def test_grind_drill_records_xp_per_step(tmp_path):
    c = ctx_of(run_dir=tmp_path, step=599)
    m = GrindDrillMonitor(13, 600, tmp_path, tmp_path / "g.jsonl", now=lambda: 2.0, xp_fn=lambda ctx: 120)
    assert m.observe(c, fr((13, 1, 1), (13, 1, 2))) is False
    c.step, c.battles, c.battles_won = 600, 4, 3
    assert m.observe(c, fr((13, 1, 2), (13, 1, 3))) and c.done
    r = m.result
    assert r["xp"] == 120 and r["xp_per_step"] == pytest.approx(0.2) and r["xp_per_min"] == pytest.approx(0.2 * 3600 / 16)
    assert r["battles"] == 4 and json.loads((tmp_path / "meta.json").read_text())["drill_result"]["kind"] == "grind"


def battle(m, lvl=10, xp=40, run="d1", **kw):
    return {"kind": 1, "map": m, "won": True, "presses": 30, "you": [0, lvl], "run": run, "hp_end": [15, 20], "turns": [{"hp_you": 20}],
            "exp_gained": [xp, 0], **kw}


def test_drill_battles_are_tagged_and_fold_into_the_atlas(tmp_path):
    stats = {}
    fold(stats, battle(13), {"starter": "S", "drill": {"kind": "grind"}})
    fold(stats, battle(13), {"starter": "S", "stop_at_goal": "beat_brock"})
    assert ("S", 8, 13, DRILL_GOAL) in stats and ("S", 8, 13, "beat_brock") in stats
    o = pooled(stats, "S", 10, 13)
    assert o.n == 2 and o.xp_sum == 80 and o.xp_n == 2        # drill battles count toward the spot's observed XP
    # through refresh: the run's meta.json carries `drill`, so its battles are folded and tagged
    (tmp_path / "d1").mkdir()
    (tmp_path / "d1" / "meta.json").write_text(json.dumps({"starter": "S", "drill": {"kind": "grind", "map": 13}}))
    (tmp_path / "battles.jsonl").write_text("".join(json.dumps(battle(13, xp=50)) + "\n" for _ in range(3)))
    kb = {"species_by_dex": {"1": {"name": "S", "base_exp": 64, "growth": "MEDIUM_SLOW"}}, "wild_by_map": {}, "name_of_internal": {}}
    assert refresh.refresh(tmp_path, kb)["folded"] == 3
    doc = json.loads((tmp_path / "grind_atlas.json").read_text())
    assert any(k.endswith(f"|{DRILL_GOAL}") for k in doc["stats"])


# ---------------------------------------------------------------- supervisor
def test_supervisor_turns_the_drill_share_of_refills_into_drills(tmp_path):
    sc_mod = _load("swarm_continuous")
    shared = tmp_path / "maps.json"
    shared.write_text("{}")
    picks, made = [], []
    pick = lambda n: (picks.append(n), {"leg": "5:2,2->4,2", "state": "s.state", "steps": 40, "key": "k"})[1]
    launched = []

    def launch(cfg):
        launched.append(cfg)
        return SimpleNamespace(poll=lambda: None, kill=lambda: None)

    sup = sc_mod.Supervisor(tmp_path, shared, 1, launch, lambda *a: None, lambda: 9, steps=400, drills=0.5, drill_pick=pick,
                            on_drill=made.append, log=lambda m: None, clock=lambda: 0.0, sleep=lambda s: None, stop_file=tmp_path / "stop")
    cfgs = [sup._config(sup.slots[0]) for _ in range(4)]
    assert [bool(c.get("drill")) for c in cfgs] == [False, True, False, True]            # F = 0.5: every second refill
    assert cfgs[1]["segment"] is None and cfgs[1]["steps"] == 42
    off = sc_mod.Supervisor(tmp_path, shared, 1, launch, lambda *a: None, lambda: 9, drill_pick=pick, log=lambda m: None, stop_file=tmp_path / "s2")
    assert off._config(off.slots[0]).get("drill") is None                                # default --drills 0: off
    none = sc_mod.Supervisor(tmp_path, shared, 1, launch, lambda *a: None, lambda: 9, drills=1.0, drill_pick=lambda n: None,
                             log=lambda m: None, stop_file=tmp_path / "s3")
    assert none._config(none.slots[0]).get("drill") is None                              # nothing drillable: a normal refill


def test_launcher_drill_args():
    sw = _load("swarm")
    assert sw.drill_args({"leg": "5:2,2->4,2", "state": "s.state"}) == ["--drill-leg", "5:2,2->4,2", "--state", "s.state"]


def test_drill_goto_steers_to_the_exit_tile(tmp_path):
    (tmp_path / "5_2_2.state").write_bytes(b"x")
    pl = attach.Plan("leg", tmp_path / "5_2_2.state", 40, D.parse("5:2,2->4,2"), 64.0)
    c = ctx_of(run_dir=tmp_path)
    c.goto = None
    attach.attach(c, pl, False, tmp_path, goto=True, drills_log=tmp_path / "d.jsonl")
    assert c.goto == [5, 4, 2] and isinstance(c.drill, D.DrillMonitor) and c.opts.steps == 42
    c2 = ctx_of(run_dir=tmp_path)
    c2.goto = None
    attach.attach(c2, pl, False, tmp_path, drills_log=tmp_path / "d.jsonl")
    assert c2.goto is None
