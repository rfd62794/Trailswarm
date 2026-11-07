"""The behaviour bandit: bucketing, Thompson choice with the Explorer prior, additive idempotent deltas, episode
reward accounting, and each decision point's override reaching the behaviour (flag off = the Explorer's own answer)."""
from __future__ import annotations

import json
import random
import threading

from pokeagent.bandit import driver as drv_mod
from pokeagent.bandit import hook, points as pt, reward as rw, table as tb
from pokeagent.bandit.driver import BanditDriver, attach
from pokeagent.bandit.store import delta_path_for, load_cells, merge_delta, write_delta
from pokeagent.explorer.behaviours import Battle
from pokeagent.explorer.behaviours.plan_goal import PlanGoal
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS

from test_explorer_behaviours import BATTLE, make_ctx, put_box


# --- context bucketing ---------------------------------------------------------------------------------------------
def test_hp_buckets_cover_the_four_quarters():
    assert [pt.hp_bucket(h, 100) for h in (0, 24, 25, 49, 50, 74, 75, 100)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert pt.hp_bucket(0, 0) == 3  # no party read: treated as healthy, never divides by zero


def test_level_gap_buckets():
    assert [pt.gap_bucket(g) for g in (-9, -3, -2, 0, 1, 3, 4, 20)] == ["le-3", "le-3", "m2_0", "m2_0", "p1_3", "p1_3", "gt3", "gt3"]


def test_context_key_has_point_stage_map_hp_gap():
    assert pt.context_key("heal", "beat_brock", 0x0D, 10, 40, -4) == "heal|beat_brock|13|1|le-3"


# --- Thompson choice honours the Explorer prior --------------------------------------------------------------------
def sub(tmp_path, name):
    (tmp_path / name).mkdir()
    return tmp_path / name


def fill(cells, key, arm, rewards):
    for r in rewards:
        tb.record(cells, key, arm, r)


def test_unvisited_or_thin_context_always_answers_the_default():
    rng = random.Random(0)
    cells: dict = {}
    for default in ("fight", "flee"):
        assert all(tb.choose(cells, "k", ("fight", "flee"), default, rng) == default for _ in range(200))
    fill(cells, "k", "fight", [-1.0] * (tb.MIN_N - 1))
    fill(cells, "k", "flee", [5.0] * 50)  # great alternative, but the default itself is still thin
    assert all(tb.choose(cells, "k", ("fight", "flee"), "fight", rng) == "fight" for _ in range(200))


def test_strong_evidence_moves_off_the_default_and_weak_evidence_does_not():
    rng = random.Random(1)
    cells: dict = {}
    fill(cells, "k", "fight", [-2.0, -2.2, -1.8, -2.1, -1.9, -2.0])
    fill(cells, "k", "flee", [-0.3, -0.2, -0.4, -0.3] * 5)
    picks = [tb.choose(cells, "k", ("fight", "flee"), "fight", rng) for _ in range(300)]
    assert picks.count("flee") > 285
    cells = {}
    fill(cells, "k", "fight", [-1.0, -1.1, -0.9, -1.0, -1.0, -1.05] * 4)
    fill(cells, "k", "flee", [-1.3, -1.4, -1.2] * 7)
    picks = [tb.choose(cells, "k", ("fight", "flee"), "fight", rng) for _ in range(300)]
    assert picks.count("fight") > 285


def test_untried_alternative_gets_explored_once_the_default_is_known():
    rng = random.Random(2)
    cells: dict = {}
    fill(cells, "k", "heal_now", [-1.0, -1.1, -0.9, -1.0, -1.0])
    picks = [tb.choose(cells, "k", ("heal_now", "push_on"), "heal_now", rng) for _ in range(400)]
    assert 40 < picks.count("push_on") < 300  # tried, but the margin keeps the default ahead


# --- deltas add up; merges never double-count ----------------------------------------------------------------------
def test_delta_cells_are_n_sum_sumsq():
    c: dict = {}
    fill(c, "k", "flee", [-1.0, 0.5])
    assert c["k"]["flee"] == [2, -0.5, 1.25]


def test_merge_adds_deltas_and_ignores_a_repeat(tmp_path):
    shared = tmp_path / "bandit.json"
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    ca: dict = {}; fill(ca, "k", "flee", [-1.0, -2.0])
    cb: dict = {}; fill(cb, "k", "flee", [0.5]); fill(cb, "k", "fight", [-3.0])
    write_delta(a, "run-a", ca); write_delta(b, "run-b", cb)
    assert merge_delta(shared, a, remove=False) and merge_delta(shared, b)
    assert not merge_delta(shared, a)  # the same delta again: already absorbed
    cells = load_cells(shared)
    assert cells["k"]["flee"] == [3, -2.5, 5.25] and cells["k"]["fight"] == [1, -3.0, 9.0]
    assert not b.exists() and not a.exists()  # merged deltas are consumed
    assert json.loads(shared.read_text())["merged"] == ["run-a", "run-b"]


def test_concurrent_merges_neither_lose_nor_double_count(tmp_path):
    shared = tmp_path / "bandit.json"
    paths = []
    for i in range(8):
        c: dict = {}; fill(c, "k", "flee", [-1.0] * 3)
        p = tmp_path / f"d{i}.json"; write_delta(p, f"run{i}", c); paths.append(p)
    paths += [tmp_path / f"d{i}.json" for i in range(8)]  # every delta is offered twice, from racing threads
    results: list = []
    def go(p):
        import shutil
        copy = tmp_path / f"copy-{threading.get_ident()}-{p.name}"
        try:
            shutil.copy(p, copy)
        except OSError:
            return
        results.append(merge_delta(shared, copy))
    threads = [threading.Thread(target=go, args=(p,)) for p in paths]
    for t in threads: t.start()
    for t in threads: t.join()
    assert load_cells(shared)["k"]["flee"] == [24, -24.0, 24.0]  # 8 runs x 3 episodes, each counted exactly once
    assert results.count(True) == 8


def test_agent_delta_path_sits_beside_its_memory(tmp_path):
    assert delta_path_for(tmp_path / "agent3-7.json").name == "agent3-7.bandit.json"


# --- reward accounting from synthetic decision records --------------------------------------------------------------
def press(outcome="moved", rule="x"):
    return {"step": 1, "rule": rule, "outcome": outcome, "map": 1}


def run_episode(records):
    ep = rw.Episode("heal", "k", "push_on", "heal_now")
    ended = [ep.add(r) for r in records]
    return ep, ended


def test_goal_ends_the_episode_with_presses_and_bonus():
    ep, ended = run_episode([press()] * 49 + [press("goal")])
    assert ended[-1] and not any(ended[:-1]) and ep.presses == 50
    assert abs(ep.reward - (-0.5 + 1.0)) < 1e-9


def test_300_presses_end_it_without_a_goal():
    ep, ended = run_episode([press()] * 400)
    assert ended.index(True) == 299 and ep.presses == 300 and abs(ep.reward + 3.0) < 1e-9
    assert ep.add(press()) is False  # a finished episode takes nothing more


def test_item_tossed_and_blackout_events_cost_but_are_not_presses():
    ep, _ = run_episode([press(), {"event": "item_tossed", "outcome": "item_tossed"}, {"event": "blackout"}, press("goal")])
    assert ep.presses == 2 and abs(ep.reward - (-0.02 - 5.0 - 3.0 + 1.0)) < 1e-9


def test_a_stall_costs_once_per_episode():
    ep, _ = run_episode([press(rule=rw.STALL_RULE), press(rule=rw.STALL_RULE), press("goal")])
    assert abs(ep.reward - (-0.03 - 2.0 + 1.0)) < 1e-9 and ep.stalled


# --- driver: episodes close into the table and the delta -----------------------------------------------------------
def test_driver_decides_once_per_situation_and_records_the_closed_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "flee")
    ctx = make_ctx(tmp_path)
    d = attach(ctx, tmp_path / "none.json", tmp_path / "delta.json", seed=0)
    assert d.decide("wild_battle", 1, lambda: "k", "fight") == "flee"
    assert d.decide("wild_battle", 1, lambda: "k", "fight") == "flee" and len(d.open) == 1  # same battle: same arm, one episode
    d.begin_step()
    d.decide("wild_battle", 1, lambda: "k", "fight")
    assert d.tag({"step": 1}) == {"step": 1, "driver": "bandit", "arm": "wild_battle=flee"}
    d.after_press(ctx, {"outcome": "moved", "rule": "r", "map": 1}, tossed=True)
    d.after_press(ctx, {"outcome": "goal", "rule": "r", "map": 1}, tossed=False)
    assert d.open == [] and d.closed == 1
    assert d.delta["k"]["flee"][0] == 1 and abs(d.delta["k"]["flee"][1] - (-0.02 - 5.0 + 1.0)) < 1e-9
    d.save()
    assert json.loads((tmp_path / "delta.json").read_text())["cells"] == d.delta


def test_driver_logs_explorer_when_it_took_the_default(tmp_path):
    d = BanditDriver(tmp_path / "none.json", tmp_path / "d.json", seed=0)
    d.begin_step()
    assert d.decide("train", "need", lambda: "k", "grind") == "grind"  # thin context: the default
    assert d.tag({"step": 2})["driver"] == "explorer" and d.tag({"step": 2})["arm"] == "train=grind"


def test_blackout_row_increase_becomes_an_event(tmp_path, monkeypatch):
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "push_on")
    ctx = make_ctx(tmp_path)
    d = attach(ctx, tmp_path / "none.json", seed=0)
    d.decide("heal", "low", lambda: "k", "heal_now")
    ctx.blackouts_row = 1
    events = d.after_press(ctx, {"outcome": "moved", "rule": "r", "map": 1, "step": 5}, tossed=False)
    assert [e["event"] for e in events] == ["blackout"]
    assert abs(d.open[0].reward - (-0.01 - 3.0)) < 1e-9


# --- flag off: the Explorer's own answers --------------------------------------------------------------------------
def test_hooks_pass_the_explorer_answer_through_when_off(tmp_path):
    ctx = make_ctx(tmp_path)
    assert ctx.bandit is None
    assert hook.wild_flee(ctx, True) is True and hook.wild_flee(ctx, False) is False
    assert hook.heal_push_on(ctx, {"deliver_parcel": True}, 3, 30) is False
    assert hook.train_need(ctx, {}, 12) == 12 and hook.train_need(ctx, {}, 0) == 0


def test_engine_lines_have_no_driver_fields_when_off_and_have_them_when_on(tmp_path):
    from pokeagent.explorer.decisions import DecisionLog
    for on in (False, True):
        d = sub(tmp_path, str(on))
        ctx = make_ctx(d)
        ctx.trans = (d / "t.jsonl").open("a", encoding="utf-8")
        on and attach(ctx, tmp_path / "none.json", seed=0)
        log = d / "decisions.jsonl"
        engine = Engine(ctx, decision_log=DecisionLog(log))
        for _ in range(3):
            engine.step()
        engine.decision_log.close(); ctx.trans.close()
        recs = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
        assert recs and all(("driver" in r) is on for r in recs)
        assert on is False or all(r["driver"] == "explorer" and r["arm"] is None for r in recs)


# --- each decision point's override reaches the behaviour ------------------------------------------------------------
def wild_ctx(tmp_path, monkeypatch, arm):
    ctx = make_ctx(tmp_path)
    ctx.emu.set(BATTLE, 1)  # wild battle
    put_box(ctx, menu=True, text_rows=(" RUN",))  # the cursor sits on RUN
    if arm:
        monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: arm)
        attach(ctx, tmp_path / "none.json", seed=0)
    ctx.refresh()
    return ctx


def test_wild_battle_override_reaches_the_battle_behaviour(tmp_path, monkeypatch):
    base = wild_ctx(sub(tmp_path, "off"), monkeypatch, None)
    assert Battle().step(base) is None and base.bv is not None  # healthy lead, no hurry: the Explorer fights
    flee = wild_ctx(sub(tmp_path, "flee"), monkeypatch, "flee")
    dec = Battle().step(flee)
    assert dec is not None and dec.rule == "flee_run" and flee.bandit.notes == [("wild_battle", "flee", True)]
    fight = wild_ctx(sub(tmp_path, "fight"), monkeypatch, "fight")
    assert Battle().step(fight) is None and fight.bv is not None and fight.bandit.notes == [("wild_battle", "fight", False)]


def test_wild_fight_arm_overrides_a_weak_flee(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, memory={0xD16C: 0, 0xD16D: 9, 0xD18D: 0, 0xD18E: 30})  # 9/30 HP (above the 25% shield): the Explorer flees
    ctx.emu.set(BATTLE, 1)
    put_box(ctx, menu=True, text_rows=(" RUN",))
    ctx.refresh()
    dec = Battle().step(ctx)
    assert dec is not None and dec.rule == "flee_run"
    ctx.in_battle = False
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "fight")
    attach(ctx, tmp_path / "none.json", seed=0)
    ctx.bandit.cells = {}  # (patched choose answers fight regardless of the table)
    ctx.refresh()
    assert Battle().step(ctx) is None and ctx.bv is not None  # the bandit chose to fight on


def test_heal_push_on_reaches_the_planner(tmp_path, monkeypatch):
    goals = {g: True for g in GOALS[:GOALS.index("to_route2") + 1]}
    goals.update(_hp=(10, 30), _level=10, _train_level=0, _heal_trips=2)
    healing = plan_step(goals, {}, (41, 2, 5), "UP")
    assert healing is not None and "HP 10/30" in healing[1]
    pushing = plan_step({**goals, "_push_on": True}, {}, (41, 2, 5), "UP")
    assert pushing is None or "HP 10/30" not in pushing[1]  # the heal rule is skipped


def test_heal_hook_applies_only_below_half_with_a_known_pokecenter(tmp_path, monkeypatch):
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "push_on")
    ctx = make_ctx(tmp_path)
    attach(ctx, tmp_path / "none.json", seed=0)
    ctx.refresh()
    goals = {"deliver_parcel": True}
    assert hook.heal_push_on(ctx, goals, 10, 30) is False  # no Pokecenter map known yet
    ctx.mem.data["maps"]["41"] = {"visited": {}}
    assert hook.heal_push_on(ctx, goals, 10, 30) is True
    assert hook.heal_push_on(ctx, goals, 25, 30) is False and "heal" not in ctx.bandit.sticky  # healthy again: choice cleared
    assert hook.heal_push_on(ctx, {}, 10, 30) is False  # the planner's heal rule is not live before the parcel


def test_plan_goal_passes_the_flag_to_the_planner(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import plan_goal as pg
    seen = {}
    monkeypatch.setattr(pg, "plan_step", lambda goals, *a: seen.update(goals) or None)
    ctx = make_ctx(tmp_path)
    ctx.refresh()
    PlanGoal().step(ctx)
    assert seen["_push_on"] is False  # off: the planner behaves as before


def test_train_skip_lifts_the_gate_in_plan_goal(tmp_path, monkeypatch):
    mem = {0xD18C: 5}  # lead level 5
    grind = make_ctx(sub(tmp_path, "g"), memory=mem)
    grind.refresh()
    PlanGoal().step(grind)
    need = grind.train_need
    assert need > 5  # the Explorer wants more levels before moving on
    skip = make_ctx(sub(tmp_path, "s"), memory=mem)
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "skip")
    attach(skip, tmp_path / "none.json", seed=0)
    skip.refresh()
    PlanGoal().step(skip)
    assert skip.train_need == 0 and skip.bandit.notes[0][:2] == ("train", "skip")
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "grind")
    keep = make_ctx(sub(tmp_path, "k"), memory=mem)
    attach(keep, tmp_path / "none.json", seed=0)
    keep.refresh()
    PlanGoal().step(keep)
    assert keep.train_need == need


def test_wild_point_skips_catch_targets(tmp_path, monkeypatch):
    from pokeagent.bandit import hook as hk
    ctx = wild_ctx(sub(tmp_path, "catch"), monkeypatch, "flee")
    monkeypatch.setattr(hk, "catch_target", lambda *a: True)
    assert hk.wild_flee(ctx, False) is False and ctx.bandit.open == []  # rules would catch: untouched, no episode
    monkeypatch.setattr(hk, "catch_target", lambda *a: False)
    assert hk.wild_flee(ctx, False) is True and len(ctx.bandit.open) == 1


def test_catch_target_needs_a_ball_and_an_unowned_species(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import battle_run as br
    monkeypatch.setattr(br, "ROM_KB", {"dex_of_internal": {"5": 7}})
    ctx = make_ctx(tmp_path)
    assert br.catch_target(ctx, 5, 3) and not br.catch_target(ctx, 5, 0)  # no ball: no catch
    ctx.emu.set(0xD2F7, 0x40)  # dex 7 owned
    assert not br.catch_target(ctx, 5, 3)


def test_fight_floor_shield_below_25_percent(tmp_path, monkeypatch):
    from pokeagent.bandit import hook as hk
    monkeypatch.setattr(hk, "catch_target", lambda *a: False)
    monkeypatch.setattr(drv_mod, "choose", lambda *a, **k: "fight")
    ctx = make_ctx(tmp_path, memory={0xD16C: 0, 0xD16D: 7, 0xD18D: 0, 0xD18E: 30})  # 7/30 = 23%
    attach(ctx, tmp_path / "none.json", seed=0)
    ctx.refresh()
    assert hk.wild_flee(ctx, False) is True and ctx.bandit.open == []
    ctx.emu.set(0xD16D, 9)  # 30%: the bandit may choose again
    assert hk.wild_flee(ctx, False) is False
