"""team_hunt: the team_ready detector, the step caps, catch_wanted's wants seam, the TeamHunt gates and walk."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokeagent import campaign
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import LearnerHunt, TeamHunt, default_behaviours
from pokeagent.explorer.catch_list import catch_wanted
from pokeagent.goals import GOALS, check_goals
from pokeagent.magikarp import GYARADOS_STEP_CAP, MAGIKARP
from test_magikarp import party_mem

STARTER = 0xB1


def _beh_ctx(goals, **kw):
    base = dict(view=SimpleNamespace(m=5, x=4, y=3, battling=False, box=False), proc=None, center_intent=None,
                blackouts_row=0, team_hunt_steps=0, hunt_grass=False, team_wants={}, team_plan=[], step=0,
                mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()), log=lambda *a, **k: None,
                goals=lambda: goals, learner_target=None, cut_learner_skipped=True)
    base.update(kw)
    return SimpleNamespace(**base)


# 1. the team_ready detector: met and sticky / skipped / nodata / open with a weak Magikarp party
def test_team_ready_detector_and_ladder_position():
    assert GOALS.index("team_ready") == GOALS.index("nugget_bridge") + 1
    assert GOALS.index("to_bill") == GOALS.index("team_ready") + 1
    assert "gyarados" not in GOALS
    assert campaign.selectable("team_ready")
    karp = FakeEmulator(party_mem([(STARTER, 14, 30, 30), (MAGIKARP, 5, 17, 17)]))
    st: dict = {}
    assert not check_goals(karp, st)["team_ready"]
    st["team_ready_ok"] = st["had_team_ready"] = True
    assert check_goals(karp, st)["team_ready"]
    st["team_ready_ok"] = False
    assert check_goals(karp, st)["team_ready"]                    # latched
    assert check_goals(karp, {"team_ready_skipped": True})["team_ready"]
    assert check_goals(karp, {"team_ready_nodata": True})["team_ready"]


# 2. the step cap settles the goal; below it stays open. The forced gate applies only for the Magikarp pick.
def test_stage_step_cap_settles_and_magikarp_only_gate():
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.magikarp import EVOLVE_LEVEL
    from pokeagent.knowledge.readiness import TEAM_GAP
    goals = {g: True for g in GOALS[:GOALS.index("team_ready")]}
    ctx = SimpleNamespace(emu=FakeEmulator(party_mem([(STARTER, 14, 30, 30)])),
                          team_ready_steps=GYARADOS_STEP_CAP - 1, team_ready_skipped=False,
                          team_plan=[], train_member=None, log=lambda *a, **k: None)
    ctx.goals = lambda: goals
    # below the cap the counter ticks and stays open; past it the goal settles
    ctx.team_ready_steps += 1
    assert ctx.team_ready_steps == GYARADOS_STEP_CAP and not ctx.team_ready_skipped
    top = SimpleNamespace(blocked="", member=SimpleNamespace(candidate=SimpleNamespace(source="wild:33")))
    ctx.team_plan = [top]
    assert PlanGoal._team_need(ctx, goals, 19) == 19             # a wild plan pick: no forced gate
    top.member.candidate = SimpleNamespace(source="magikarp")
    assert PlanGoal._team_need(ctx, goals, 19) == 19             # a Magikarp pick with no MAGIKARP in the party: no gate
    ctx.emu = FakeEmulator(party_mem([(STARTER, 14, 30, 30), (MAGIKARP, 5, 17, 17)]))
    assert PlanGoal._team_need(ctx, goals, 19) >= EVOLVE_LEVEL + TEAM_GAP
    top.blocked = "no balls"                                     # the first NON-blocked action decides
    assert PlanGoal._team_need(ctx, goals, 19) == 19


# 3. catch_wanted's wants seam and catch.py's admit condition
def test_catch_wanted_wants_seam():
    why = catch_wanted("NIDORAN(M)", ["SQUIRTLE"], 5, [], wants={"NIDORAN(M)": "planned: value 1.4 (contributes to MISTY)"})
    assert why == "planned: value 1.4 (contributes to MISTY)"
    assert catch_wanted("NIDORAN(M)", ["SQUIRTLE"], 5, [], wants=None) is None
    assert catch_wanted("NIDORAN(M)", ["SQUIRTLE"], 5, [], wants={"PIKACHU": "planned: x"}) is None
    want = "planned: new species 8/10 toward the Pokedex gate, 140 steps"
    assert want.startswith("planned")                            # catch.py's admit condition accepts it


# 4. the gates
def _ok_ctx():
    emu_mem = {**party_mem([(STARTER, 18, 51, 51)]), 0xD31D: 2, 0xD31E: 0x04, 0xD31F: 3, 0xD320: 0x14, 0xD321: 1}
    ctx = _beh_ctx({"hm01_cut": False}, emu=FakeEmulator(emu_mem))
    ctx.view.m = 0x0C
    return ctx


def test_applies_gates():
    h = TeamHunt()
    bad = _beh_ctx({"hm01_cut": False}, view=SimpleNamespace(m=5, x=4, y=3, battling=True, box=False))
    assert not h.applies(bad)                                                    # battling
    boss = _ok_ctx(); boss.goals = lambda: {g: g != "beat_brock" for g in GOALS}  # next unmet is a boss goal
    assert not h.applies(boss)
    ship = _ok_ctx(); ship.view.m = 0x5E
    assert not h.applies(ship)
    noheal = _ok_ctx(); noheal.emu.set(0xD31D, 1)
    assert not h.applies(noheal)                                                 # no heal items
    noball = _ok_ctx(); noball.emu.set(0xD31F, 0)
    assert not h.applies(noball)                                                 # no balls
    weak = _ok_ctx(); weak.emu.memory.update({0xD16C: 0, 0xD16D: 10})
    assert not h.applies(weak)                                                   # HP below TEAM_HUNT_MIN_HP
    row = _ok_ctx(); row.blackouts_row = 1
    assert not h.applies(row)
    capped = _ok_ctx(); capped.team_hunt_steps = 3001
    assert not h.applies(capped)
    full = _ok_ctx(); full.emu.memory.update(party_mem([(STARTER, 18, 51, 51)] * 6))
    assert not h.applies(full)
    # it must not clear a hunt_grass that learner_hunt set
    c = _ok_ctx()
    c.goals = lambda: {"hm01_cut": True, "cut_learner": False}
    c.cut_learner_skipped, c.hunt_grass = False, True
    h2 = TeamHunt(); h2.applies(c)
    assert c.hunt_grass


def test_gated_out_applies_do_not_advance_the_step_counter_and_clear_the_plan():
    h = TeamHunt()
    c = _ok_ctx(); c.emu.set(0xD31F, 0)                                          # no balls: gated out
    c.team_plan = ["stale"]
    for _ in range(50):
        assert not h.applies(c)
    assert c.team_hunt_steps == 0 and c.team_plan == []


def test_gate_blip_then_pass_rebuilds_immediately():
    h = TeamHunt(); c = _ok_ctx(); c.step = 10
    h.applies(c)
    assert h._plan_key is not None
    c.emu.set(0xD31F, 0)                                                         # blip: no balls
    assert not h.applies(c) and h._plan_key is None
    c.emu.set(0xD31F, 3); c.step = 11
    built = []
    h._refresh = lambda *a: built.append(1)
    h.applies(c)
    assert built                                                                 # rebuilt on the very next passing step


def test_owned_magikarp_pick_fires_team_need():
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.knowledge.catch_plan import plan_catches
    from pokeagent.magikarp import EVOLVE_LEVEL
    from pokeagent.knowledge.readiness import TEAM_GAP
    import test_catch_plan as tc
    plan = tc._plan(party=[tc._mon("PIDGEY", 20), tc._mon("MAGIKARP", 15)], bosses=[("HARD", [(22, "ONIX")])],
                    magikarp_level=15, owned_species={"PIDGEY"}, xp_for_map=lambda m: 130)
    goals = {g: True for g in GOALS[:GOALS.index("team_ready")]}
    ctx = SimpleNamespace(emu=FakeEmulator(party_mem([(STARTER, 14, 30, 30), (MAGIKARP, 5, 17, 17)])),
                          team_plan=plan, train_member=None)
    assert plan[0].species == "MAGIKARP" and plan[0].member.candidate.source == "magikarp"
    assert PlanGoal._team_need(ctx, goals, 19) >= EVOLVE_LEVEL + TEAM_GAP


def test_announce_once_per_target():
    from pokeagent.knowledge.catch_plan import CatchAction
    logs = []
    act = CatchAction("NIDORAN(M)", 0x21, "Route 22", (2, 4), 0.395, 25, 1.3, 310, 60, 3, "", 20,
                      SimpleNamespace(candidate=SimpleNamespace(source="wild:33"), contributes=("MISTY",)))
    h = TeamHunt(); ctx = _ok_ctx(); ctx.team_plan = [act]; ctx.view.m = 0x21
    ctx.log = lambda *a, **k: logs.append(a)
    for _ in range(5):
        h.step(ctx)
    assert len(logs) == 1 and ctx.team_hunt_steps == 5


# 5. the walk
def test_step_walks_arms_grass_and_bounds():
    from pokeagent.explorer.behaviours.team_hunt import TEAM_HUNT_BUDGET
    from pokeagent.knowledge.catch_plan import CatchAction
    h = TeamHunt()
    act = CatchAction("NIDORAN(M)", 0x21, "Route 22", (2, 4), 0.395, 25, 1.3, 310, 60, 3, "", 20,
                      SimpleNamespace(candidate=SimpleNamespace(source="wild:33"), contributes=("MISTY",)))
    ctx = _ok_ctx(); ctx.team_plan = [act]
    ctx.view.m = 0x21
    assert h.step(ctx) is None and ctx.hunt_grass and h._armed                       # on the map: grass armed
    ctx.view.m = 5; ctx.hunt_grass = False; h._armed = False
    assert h.step(ctx) is None                                                     # no route known -> None
    far = CatchAction("ODDISH", 0x23, "Route 24", (12, 14), .246, 25, 1.3, 900, 10, 3, "", TEAM_HUNT_BUDGET + 1,
                      SimpleNamespace(contributives=(), candidate=SimpleNamespace(source="wild:35"), contributes=()))
    ctx.team_plan = [far]
    assert h.step(ctx) is None                                                     # detour over budget -> None

    class G:
        blocked_now = frozenset()
        def __init__(self, *_a): pass
        def path(self, _s, goal): return ["UP", "UP"] if goal((0x21, 0, 0)) else None
    import pokeagent.explorer.behaviours.team_hunt as th
    wg = th.WorldGraph; th.WorldGraph = G
    try:
        ctx.team_plan = [act]
        d = h.step(ctx)
        assert d is not None and d.button == "UP" and d.rule == "team_hunt_walk"
    finally:
        th.WorldGraph = wg


# 6. the behaviour order: TeamHunt after LearnerHunt, before Frontier
def test_behaviour_order():
    names = [b.name for b in default_behaviours()]
    assert names.index("learner_hunt") < names.index("team_hunt") < names.index("frontier")


# 7. PR #165: a live grind episode pins the run to its map set - the hunts do not apply during one
def test_a_live_grind_episode_pauses_the_hunt():
    h = TeamHunt(); c = _ok_ctx()
    c._grind_state = {"episode": {"maps": {c.view.m}, "point": None}}
    assert not h.applies(c)                                          # an outside-set target is not pursued
