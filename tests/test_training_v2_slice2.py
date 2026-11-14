"""Training v2 slice 2 (2026-11-13 laptop A/B): the shake exemption reaches every training path and is capped; a Harden
cocoon is run from while levelling; the unmet team floor is never released by a ceiling lift or the sim alone."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import grind_loop, low_yield, plan_goal
from pokeagent.explorer.behaviours.guards import LoopGuard
from pokeagent.explorer.behaviours.plan_goal import PlanGoal
from pokeagent.explorer.grind import stall_hold_holds
from pokeagent.explorer.training_ctl.controller import TrainingController
from pokeagent.knowledge import team_floor
from test_battle_types import BATTLE, make_ctx
from test_grind_pressure_plan_goal import _full_ctx, _gate_patch

PX = 0xD362


def _replay(tmp_path, steps, *, live, battle_every=40):
    """team_ready grass walk -> battle -> pacing on 2 tiles -> battle ..., through the REAL LoopGuard."""
    ctx = make_ctx(tmp_path, memory={BATTLE: 0})
    ctx.train_route_live = live
    for i in range(steps):
        in_fight = i % battle_every < 6 and i >= 10          # a short fight every `battle_every` presses
        if in_fight and i % battle_every == 0:
            ctx.battles += 1                                   # Battle.step counts a fight when it starts
        ctx.emu.set(BATTLE, 1 if in_fight else 0)
        ctx.emu.set(PX, 4 + i % 2)                             # pacing between two tiles
        ctx.refresh()
        LoopGuard().step(ctx)
    return ctx


def test_replay_pacing_between_battles_is_not_shaken(tmp_path):
    assert _replay(tmp_path, 170, live=True).shakes == 0       # one pace window's worth, a battle in every window


def test_replay_without_the_training_flag_shakes(tmp_path):
    """The bug: the hold / grind-latch walk to the grass never set the flag, so the same pace shook (#235 never fired)."""
    assert _replay(tmp_path, 170, live=False).shakes >= 1


def test_exemption_is_capped_at_three_windows(tmp_path):
    c = _replay(tmp_path, 400, live=True)
    assert 1 <= c.shakes <= 3                                  # 3 windows spared, then one shake, not unbounded


def test_hold_and_grind_latch_walk_marks_training_live(monkeypatch):
    ctx = SimpleNamespace(train_route_live=False, stage_goal="beat_misty", mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()),
                          emu=None, view=SimpleNamespace(m=3), step=10, train_need=0, goals=lambda: {})
    monkeypatch.setattr(plan_goal, "party_survives", lambda emu, m: True)
    monkeypatch.setattr(plan_goal.grind_episode, "start", lambda c, reason="x": False)
    monkeypatch.setattr(plan_goal.train_route, "step", lambda *a, **k: None)
    assert PlanGoal._grind_step(ctx, 3, 2, 4, 30, 40) is None and ctx.__dict__.get("grind_walk_step") is None
    monkeypatch.setattr(plan_goal.train_route, "step", lambda *a, **k: ("UP", "goal team_ready: 9 steps to Route 24's grass"))
    assert PlanGoal._grind_step(ctx, 3, 2, 4, 30, 40) is not None and ctx.__dict__.get("grind_walk_step") == 10
    TrainingController().tick(ctx)   # the stamp is a step old at worst: tick turns it into the flag
    assert ctx.train_route_live is True
    ctx2 = SimpleNamespace(train_route_live=False, step=11, train_need=0, goals=lambda: {})
    TrainingController().tick(ctx2)  # no stamp, not team_ready: the flag stays down
    assert ctx2.train_route_live is False


def test_a_grind_episode_pace_counts_as_training(tmp_path):
    ctx = make_ctx(tmp_path, memory={BATTLE: 0})
    ctx.train_route_live = False
    ctx.__dict__["_grind_state"] = {"episode": {"maps": {0x23}}}
    for i in range(70):
        if i == 20:
            ctx.battles += 1
        grind_loop.note_step(ctx)
    assert grind_loop.paced_in_training(ctx)


# --- lever: run from a Harden cocoon ----------------------------------------------------------------------------------

def _cocoon_ctx(monkeypatch, grinding=True, runs=0):
    monkeypatch.setattr(low_yield, "ROM_KB", {"name_of_internal": {"1": "KAKUNA", "2": "PIDGEY", "3": "METAPOD"}})
    monkeypatch.setattr(low_yield, "grinding", lambda ctx: grinding)
    monkeypatch.setattr(low_yield, "catch_target", lambda ctx, sp, balls: False)
    return SimpleNamespace(cave_runs=runs)


def test_run_from_a_cocoon_while_levelling(monkeypatch):
    ctx = _cocoon_ctx(monkeypatch)
    assert low_yield.stall_run(ctx, 1, 1) and low_yield.stall_run(ctx, 1, 3)
    assert not low_yield.stall_run(ctx, 1, 2)                  # a Pidgey is XP: fight
    assert not low_yield.stall_run(ctx, 2, 1)                  # trainer fights cannot be left


def test_cocoon_rule_needs_training_a_budget_and_no_catch(monkeypatch):
    assert not low_yield.stall_run(_cocoon_ctx(monkeypatch, grinding=False), 1, 1)
    assert not low_yield.stall_run(_cocoon_ctx(monkeypatch, runs=low_yield.MAX_CAVE_RUNS), 1, 1)  # a failed escape fights on
    ctx = _cocoon_ctx(monkeypatch)
    monkeypatch.setattr(low_yield, "catch_target", lambda c, sp, balls: True)
    assert not low_yield.stall_run(ctx, 1, 1)


# --- floor bypass -----------------------------------------------------------------------------------------------------

def test_ceiling_lift_does_not_open_a_gym_while_the_floor_is_unmet():
    st = {}
    why = "the lead reached the level ceiling"
    assert not stall_hold_holds(st, why, 0, 0)                  # floor met: a ceiling lift releases, as before
    assert stall_hold_holds({}, why, 0, 0, floor_unmet=True)    # floor unmet (19 x2): the strongest member says nothing


def test_unmet_floor_with_a_spent_ceiling_budget_keeps_the_hold(tmp_path, monkeypatch):
    """Fresh-runs bug: team_ready settled on the sim, the budget lifted on the L26 fighter's ceiling, the gym hold went
    False and goal_talk walked to Misty with the team under the floor. The hold must stand and grind / look for grass."""
    ctx = _full_ctx(tmp_path)
    _gate_patch(monkeypatch)
    unmet = team_floor.Floor(False, 19, 2, 1, 0, "team floor for beat_misty: need 2 members >= L19, have 1")
    monkeypatch.setattr("pokeagent.explorer.training.floor_for", lambda goals, party: unmet)
    monkeypatch.setattr(plan_goal, "level_ceiling", lambda stage: 3)   # the strongest member is over the ceiling
    ctx.mem.data["maps"]["3"] = {"visited": {"2,4": 1}, "warps": {"2,4,UP": [0x41, 4, 6]}}
    for step in (0, 50, 400):
        ctx.step = step
        d = PlanGoal().step(ctx)
        assert d is None or d.button != "UP"
        assert ctx.gym_hold_seen[1] is True


def test_the_sim_alone_does_not_settle_team_ready_while_the_floor_is_unmet():
    src = open(plan_goal.__file__).read()
    assert 'elif team.ready and not ctx.__dict__.get("floor_unmet")' in src
