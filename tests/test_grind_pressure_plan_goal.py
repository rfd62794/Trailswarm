"""plan_goal's grind-pressure consumption: the latch thresholds, the boss-distance term and the
grind/gym-hold decision helpers. All contexts are synthetic (no ROM, no emulator).
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import plan_goal
from pokeagent.explorer.behaviours.plan_goal import PlanGoal
from pokeagent.explorer.grind import GRIND_BATTLES
from pokeagent.explorer.training_ctl import sustain
from pokeagent.knowledge import team_plan


def _ctx(stage_goal="beat_misty", maps=None):
    return SimpleNamespace(stage_goal=stage_goal, emu=None, view=SimpleNamespace(m=0x03), step=0,
                           mem=SimpleNamespace(data={"maps": maps or {}}, temp_blocked={}))


def test_boss_gap_counts_learned_steps_to_the_gym():
    # map 0x03 tile (2,4) UP is a learned warp onto Misty's gym (0x41): the boss is one step away
    ctx = _ctx(maps={"3": {"visited": {"2,4": 1}, "warps": {"2,4,UP": [65, 5, 5]}}})
    assert PlanGoal._boss_gap(ctx, 0x03, 2, 4) == 1


def test_boss_gap_unknown_is_far_not_urgent():
    ctx = _ctx(maps={})
    assert PlanGoal._boss_gap(ctx, 0x03, 2, 4) == team_plan.NEAR_STEPS
    # a stage with no gym map reads the same as "far away"
    assert PlanGoal._boss_gap(_ctx(stage_goal="to_route3"), 0x0E, 5, 5) == team_plan.NEAR_STEPS


def test_enters_detects_a_planned_press_into_the_gym():
    ctx = _ctx(maps={"3": {"visited": {"2,4": 1}, "warps": {"2,4,UP": [65, 5, 5]}}})
    assert PlanGoal._enters(ctx, 0x03, 2, 4, ("UP", "goal beat_misty: 1 steps"), 0x41)
    assert not PlanGoal._enters(ctx, 0x03, 2, 4, ("DOWN", "goal beat_misty: 1 steps"), 0x41)
    assert not PlanGoal._enters(ctx, 0x03, 2, 4, ("A", "goal beat_misty: at the door"), 0x41)


def test_grind_step_uses_train_route_when_no_episode_starts(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(plan_goal, "party_survives", lambda emu, m: True)
    monkeypatch.setattr(plan_goal.grind_episode, "start", lambda c, reason="x": False)
    monkeypatch.setattr(plan_goal.train_route, "step", lambda maps, pos, blocked, hp, mx, **kw: ("UP", "to Route 24 grass"))
    assert PlanGoal._grind_step(ctx, 0x03, 2, 4, 30, 40) == ("UP", "to Route 24 grass")
    monkeypatch.setattr(plan_goal.train_route, "step", lambda maps, pos, blocked, hp, mx, **kw: None)
    assert PlanGoal._grind_step(ctx, 0x03, 2, 4, 30, 40) is None


def test_real_grind_step_handles_start_returning_a_bool(monkeypatch):
    """grind_episode.start returns bool (never a step): the REAL _grind_step must not index it, and must hand
    back a real train_route decision for BOTH outcomes (True: the episode owns the next tick; False: no episode)."""
    ctx = _ctx()
    monkeypatch.setattr(plan_goal, "party_survives", lambda emu, m: True)
    seen = []
    monkeypatch.setattr(plan_goal.train_route, "step", lambda maps, pos, blocked, hp, mx, **kw: ("UP", "to Route 24 grass"))
    for outcome in (True, False):
        monkeypatch.setattr(plan_goal.grind_episode, "start", lambda c, reason="x", o=outcome: seen.append(o) or o)
        assert PlanGoal._grind_step(ctx, 0x03, 2, 4, 30, 40) == ("UP", "to Route 24 grass")
    assert seen == [True, False]


def test_pressure_thresholds_bound_the_latch():
    assert team_plan.GRIND_PRESSURE_START > team_plan.GRIND_PRESSURE_STOP > 0
    team = [SimpleNamespace(level=10) for _ in range(4)]
    p = team_plan.grind_pressure(team, 25, next_boss_gap_steps=5, blackouts_recent=2,
                                 breakers=(1, 2, 3), lead_level=10)
    assert p >= team_plan.GRIND_PRESSURE_START     # a big weak team at the boss's door grinds
    p0 = team_plan.grind_pressure(team, 10, lead_level=10)
    assert p0 < team_plan.GRIND_PRESSURE_STOP      # no gap, no breakers: the latch releases


# --- the gym hold branch of PlanGoal.step (nv not ready + a GYM_BOSSES map) -------------------------------------------

def _full_ctx(tmp_path, mem_map=0x03, x=2, y=4, level=5):
    """A real ExplorerContext on a FakeEmulator for PlanGoal().step (no ROM, overworld frame)."""
    from pokeagent.emulator import FakeEmulator
    from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
    from pokeagent.explorer.memory import MapMemory
    emu = FakeEmulator({0xD35E: mem_map, 0xD362: x, 0xD361: y, 0xD18C: level})   # 0xD18C = lead's level
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=10)
    ctx.refresh()
    return ctx


def _gate_patch(monkeypatch, *, grind=("DOWN", "team gate: grinding the party")):
    """Pin the seams PlanGoal.step reads to 'team not ready vs MISTY, the planner wants UP'."""
    nv = SimpleNamespace(ready=False, need=15, text="team not ready vs MISTY", team_score=-0.4,
                         weak_slots=(0,), lead_slot=0)
    monkeypatch.setattr(plan_goal, "boss_need_for", lambda goals, party: nv)
    monkeypatch.setattr(plan_goal, "readiness_for", lambda goals, party: SimpleNamespace(text="", score=0.0, required=15))
    monkeypatch.setattr(plan_goal, "team_for", lambda goals, party: None)
    monkeypatch.setattr(plan_goal, "required_level", lambda goals, floor, party: (15, ""))
    monkeypatch.setattr(plan_goal, "under_level_note", lambda *a: "")
    monkeypatch.setattr("pokeagent.explorer.training.floor_for", lambda goals, party: None)  # fake nv/party: the team floor is team_floor tests
    monkeypatch.setattr(plan_goal, "stage_goal", lambda goals: "beat_misty")
    monkeypatch.setattr(plan_goal, "plan_step", lambda goals, maps, pos, facing: ("UP", "goal beat_misty: 1 steps"))
    monkeypatch.setattr(plan_goal, "our_party", lambda emu: [SimpleNamespace(name="TURTLE", level=5)])
    monkeypatch.setattr(sustain, "heal_push_on", lambda *a, **k: False)
    monkeypatch.setattr(plan_goal, "train_need", lambda ctx, goals, need: need)
    monkeypatch.setattr(plan_goal, "level_ceiling", lambda stage: None)
    monkeypatch.setattr(PlanGoal, "_grind_step", staticmethod(lambda *a: grind))


def test_gym_hold_grinds_instead_of_entering_while_the_budget_lasts(tmp_path, monkeypatch):
    ctx = _full_ctx(tmp_path)
    _gate_patch(monkeypatch)
    ctx.mem.data["maps"]["3"] = {"visited": {"2,4": 1}, "warps": {"2,4,UP": [0x41, 4, 6]}}  # UP enters Misty's gym
    d = PlanGoal().step(ctx)
    assert d.button == "DOWN" and d.rule == "plan_goal"      # the hold: grind, do not walk in


def test_a_spent_stall_budget_keeps_the_gym_hold_so_the_team_leaves_to_grind(tmp_path, monkeypatch):
    ctx = _full_ctx(tmp_path)
    _gate_patch(monkeypatch)
    ctx.mem.data["maps"]["3"] = {"visited": {"2,4": 1}, "warps": {"2,4,UP": [0x41, 4, 6]}}
    PlanGoal().step(ctx)                                     # budget starts accruing (0 battles so far)
    ctx.step, ctx.battles = 300, GRIND_BATTLES               # the whole battle budget in one delta
    lines = []
    ctx.log = lambda text, tag=None: lines.append(text)
    d = PlanGoal().step(ctx)
    assert d.button != "UP"                                  # stalled budget, team not ready: the stage push must not walk in
    assert not any("gym hold lifted" in ln for ln in lines)  # the hold stands (the gym stays shut until ready)


def test_inside_the_gym_not_ready_walks_out_before_anything_else(tmp_path, monkeypatch):
    ctx = _full_ctx(tmp_path, mem_map=0x41, x=4, y=5)
    _gate_patch(monkeypatch)
    ctx.mem.data["maps"]["65"] = {"visited": {"4,5": 1, "4,6": 1}, "warps": {"4,6,DOWN": [3, 30, 19]}}
    d = PlanGoal().step(ctx)
    assert d.button == "DOWN" and "out of the gym" in d.why  # the learned exit, not the grind route


def test_out_step_first_press_off_the_gym_map():
    maps = {"65": {"visited": {"4,5": 1, "4,6": 1}, "warps": {"4,6,DOWN": [3, 30, 19]}}}
    assert PlanGoal._out_step(_ctx(maps=maps), 0x41, 4, 5, 0x41) == ("DOWN", "team gate: not ready - 2 steps out of the gym")
    assert PlanGoal._out_step(_ctx(maps={}), 0x41, 4, 5, 0x41) is None   # no learned exit: frontier still decides


def test_leader_avoid_blocks_the_guessed_sight_line(tmp_path, monkeypatch):
    from pokeagent.explorer import trainer_hooks, trainer_route
    from pokeagent.explorer.trainer_ledger import TrainerLedger
    maps = {"65": {"visited": {f"4,{y}": 1 for y in range(1, 7)}, "warps": {"4,6,DOWN": [3, 30, 19]}}}
    ctx = SimpleNamespace(mem=SimpleNamespace(data={"maps": maps}, temp_blocked={}),
                          view=SimpleNamespace(m=0x41, x=4, y=5), frame=0, run_dir=str(tmp_path),
                          log=lambda *a, **k: None)
    led = TrainerLedger({0x41: [{"class": "MISTY", "party": 1, "x": 4, "y": 1, "mons": [(21, "STARMIE")]}]})
    monkeypatch.setattr(trainer_hooks, "ledger_for", lambda c: led)
    monkeypatch.setattr(trainer_hooks, "current_party", lambda c: [])
    monkeypatch.setattr(trainer_route, "fight_margin", lambda *a, **k: -1.0)   # the sim loses: avoid
    PlanGoal._leader_avoid(ctx, 0x41, 4, 5, 0x41)
    assert (0x41, 4, 4) in ctx.mem.temp_blocked                # the leader's column is routing-blocked
    assert (0x41, 4, 6) not in ctx.mem.temp_blocked            # ... while the exit walk stays open
    assert team_plan.of(ctx)["avoid_key"] is not None
    PlanGoal._leader_avoid(ctx, 0x03, 4, 5, 0x41)              # off the gym map: a no-op


def test_gym_hold_replaces_the_road_to_the_gym_with_the_grind_step(tmp_path, monkeypatch):
    """Pewter, not ready: the planner's 'goal road north' toward the gym map must not win over the hold."""
    ctx = _full_ctx(tmp_path, mem_map=0x02)
    _gate_patch(monkeypatch, grind=("LEFT", "team gate: grinding the party"))
    monkeypatch.setattr(plan_goal, "stage_goal", lambda goals: "beat_brock")
    monkeypatch.setattr(plan_goal, "plan_step", lambda goals, maps, pos, facing: ("UP", "goal road north: 9 steps to map 0x36"))
    d = PlanGoal().step(ctx)
    assert d.button == "LEFT" and "grinding" in d.why


def test_a_held_stall_lift_keeps_the_episode_gate_open(tmp_path, monkeypatch):
    ctx = _full_ctx(tmp_path, mem_map=0x02)
    _gate_patch(monkeypatch)
    monkeypatch.setattr(plan_goal, "stage_goal", lambda goals: "beat_brock")
    monkeypatch.setattr(plan_goal, "train_need", lambda c, g, n: n)
    ctx.mem.data["maps"]["2"] = {"encounters": {"1,1": 3}}          # grass here, so the budget accrues
    PlanGoal().step(ctx)
    ctx.step, ctx.battles = 300, 99
    PlanGoal().step(ctx)
    assert ctx.train_need == 15                                      # lifted, held, yet the episode gate still reads the need


def test_hold_cap_releases_even_when_the_budget_never_lifts(tmp_path, monkeypatch):
    """No learned encounters, no episode: grinding_now is False so the budget never accrues; the cap still bounds the hold."""
    from pokeagent.explorer.grind import STALL_HOLD_CAP
    ctx = _full_ctx(tmp_path)
    _gate_patch(monkeypatch)
    ctx.mem.data["maps"]["3"] = {"visited": {"2,4": 1}, "warps": {"2,4,UP": [0x41, 4, 6]}}   # no "encounters" here
    ctx.step = 100
    d = PlanGoal().step(ctx)
    assert d.button != "UP" and plan_goal.team_plan.of(ctx).get("gate_lifted") is None       # held, budget idle
    ctx.step = 100 + STALL_HOLD_CAP - 1
    assert PlanGoal().step(ctx).button != "UP"
    lines = []
    ctx.log = lambda text, tag=None: lines.append(text)
    ctx.step = 100 + STALL_HOLD_CAP
    PlanGoal().step(ctx)
    assert any("gym hold lifted" in ln for ln in lines)                                      # the cap opens the gym


def _held_ctx(tmp_path, monkeypatch):
    ctx = _full_ctx(tmp_path)
    _gate_patch(monkeypatch)
    ctx.mem.data["maps"]["3"] = {"visited": {"2,4": 1}, "warps": {"2,4,UP": [0x41, 4, 6]}}
    ctx.step = 100
    PlanGoal().step(ctx)
    return ctx


def test_battle_frames_and_a_readiness_flap_do_not_reset_the_hold_clock(tmp_path, monkeypatch):
    ctx = _held_ctx(tmp_path, monkeypatch)
    st = plan_goal.team_plan.of(ctx)
    assert st["stall_hold"][0] == 100
    monkeypatch.setattr(plan_goal, "boss_need_for", lambda goals, party: None)     # battle frame: party unread, nv None
    ctx.step = 200
    PlanGoal().step(ctx)
    ready = SimpleNamespace(ready=True, need=15, text="ready", team_score=1.0, weak_slots=(), lead_slot=0)
    monkeypatch.setattr(plan_goal, "boss_need_for", lambda goals, party: ready)    # one-step flap to ready
    ctx.step = 300
    PlanGoal().step(ctx)
    assert st["stall_hold"][0] == 100                                              # still the first engagement
    monkeypatch.setattr(plan_goal, "stage_goal", lambda goals: "beat_brock")       # the stage moved on: now it clears
    ctx.step = 400
    PlanGoal().step(ctx)
    assert "stall_hold" not in st or st["stall_hold"][0] != 100


def test_a_blackout_after_a_win_still_releases_the_hold(tmp_path, monkeypatch):
    ctx = _held_ctx(tmp_path, monkeypatch)
    pl = plan_goal.party_log.of(ctx)
    pl.blackouts += 1                                                              # blackout while held...
    ctx.blackouts_row = 0                                                          # ...then a win zeroes the row counter
    lines = []
    ctx.log = lambda text, tag=None: lines.append(text)
    ctx.step = 200
    PlanGoal().step(ctx)
    assert any("gym hold lifted" in ln for ln in lines)
