"""Team readiness: the whole party vs the boss (hurt-lead sim), the gyarados ladder goal, the training-gate
level seam, and who the switch-training targets."""
from __future__ import annotations

from pokeagent import campaign
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.perceive import lead_level
from pokeagent.explorer.stats import stat_value
from pokeagent.goals import GOALS, SIDE_GOALS, check_goals
from pokeagent.knowledge.party import Combatant
from pokeagent.knowledge.readiness import TEAM_GAP, team_readiness
from pokeagent.magikarp import GYARADOS, MAGIKARP, trainee_slot_for
from test_magikarp import party_mem


def _mv(name, typ, power, acc=1.0, effect=0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": effect, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc, "moves1": moves1}


# The test_knowledge.SYN cartridge plus the trainee pair and a bulky WATER boss for the hurt-lead case.
SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40), "3": _mv("EMBER", "FIRE", 40, effect=4)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["FIRE", "ROCK", 0.5], ["WATER", "WATER", 0.5]],
    "species_by_dex": {"1": _species("AQUA", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
                       "2": _species("BLAZE", "FIRE", "FIRE", 44, 48, 65, 43, 50, ["TACKLE"]),
                       "3": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"]),
                       "4": _species("MAGIKARP", "WATER", "WATER", 15, 5, 40, 50, 10, ["TACKLE"]),
                       "5": _species("GYARADOS", "WATER", "FLYING", 95, 125, 79, 81, 100, ["TACKLE"]),
                       "6": _species("TURTLE", "WATER", "WATER", 100, 60, 90, 60, 60, ["TACKLE"])},
    "learnsets": {"AQUA": {"learnset": [[8, "WATER GUN"]]}, "BLAZE": {"learnset": [[8, "EMBER"]]}, "PEBBLE": {"learnset": []},
                  "MAGIKARP": {"learnset": []}, "GYARADOS": {"learnset": [[20, "WATER GUN"]]}, "TURTLE": {"learnset": []}},
}

BOSS = [(12, "PEBBLE"), (14, "PEBBLE")]   # a synthetic two-mon boss
TANK = [(20, "TURTLE")]                   # bulky enough that the half-HP lead loses where the full one wins


def _mon(name, level, moves=None):
    """A Combatant built like test_knowledge._starter, for any species in this file's SYN."""
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    types = tuple(dict.fromkeys((row["type1"], row["type2"])))
    return Combatant(name, level, types, hp, st, tuple(moves if moves is not None else row["moves1"]), (8,) * 5, (0,) * 5)


# --- the party verdict -------------------------------------------------------------------------------------------

def test_weak_second_member_names_the_trainee_shortfall():
    t = team_readiness([_mon("AQUA", 30), _mon("MAGIKARP", 13)], BOSS, "TWO-MON", SYN)
    assert t is not None and t.ready is False
    assert t.weakest is not None and t.weakest.name == "MAGIKARP" and t.weakest.useful is False
    assert t.weakest.target >= 20 and t.weakest.target >= 30 - TEAM_GAP
    assert t.text.startswith("team not ready vs TWO-MON: MAGIKARP L13 -> L")


def test_strong_second_member_makes_the_team_ready():
    t = team_readiness([_mon("AQUA", 30), _mon("BLAZE", 28)], BOSS, "TWO-MON", SYN)
    assert t is not None and t.ready is True and t.weakest is None
    assert all(m.useful for m in t.members)
    assert t.text == "team ready vs TWO-MON: lead L30, 2/2 useful"


def test_one_mon_and_empty_inputs():
    t = team_readiness([_mon("AQUA", 30)], BOSS, "TWO-MON", SYN)
    assert t is not None and t.ready is False and t.weakest is None
    assert "no second member" in t.text
    assert team_readiness([], BOSS, "X", SYN) is None
    assert team_readiness([_mon("AQUA", 30)], [], "X", SYN) is None


def test_hurt_lead_sim_fails_where_the_full_lead_wins():
    t = team_readiness([_mon("AQUA", 30), _mon("MAGIKARP", 13)], TANK, "TANK", SYN)
    assert t is not None and t.lead is not None and t.lead.ready is True   # assess passes at full HP ...
    assert t.ready is False                                                # ... but the half-HP lead loses and the trainee cannot fight


def test_evolved_magikarp_is_judged_as_gyarados():
    t = team_readiness([_mon("AQUA", 26), _mon("MAGIKARP", 22)], BOSS, "TWO-MON", SYN)
    assert t is not None
    karp = next(m for m in t.members if m.name == "MAGIKARP")
    assert karp.useful is True   # L22 >= EVOLVE_LEVEL: the GYARADOS projection carries the hurt-lead sim


# --- the team_ready ladder goal (was the gyarados mandate) ---------------------------------------------------------

def test_team_ready_detector_never_blocks():
    assert GOALS.index("team_ready") == GOALS.index("nugget_bridge") + 1
    assert GOALS.index("to_bill") == GOALS.index("team_ready") + 1
    assert "gyarados" not in GOALS and "team_ready" not in SIDE_GOALS
    assert campaign.selectable("team_ready")   # the segment picker may target it: nugget_bridge -> team_ready
    karp = FakeEmulator(party_mem([(0xB1, 14, 30, 30), (MAGIKARP, 5, 17, 17)]))
    st: dict = {}
    assert not check_goals(karp, st)["team_ready"]                # open while the sim has not said ready
    st["team_ready_ok"] = True
    assert check_goals(karp, st)["team_ready"]                    # plan_goal's verdict: the party beats the next boss
    st["team_ready_ok"] = False
    assert check_goals(karp, st)["team_ready"]                    # sticky via had_team_ready (set by plan_goal on the latch)
    assert check_goals(karp, {"team_ready_skipped": True})["team_ready"]  # the stage's step cap ran out
    assert check_goals(karp, {"team_ready_nodata": True})["team_ready"]   # no boss data: never blocks


# --- the training-gate seam and the switch-training target --------------------------------------------------------

def test_lead_level_is_the_strongest_member_not_slot_0_and_not_the_trainee_band():
    emu = FakeEmulator(party_mem([(MAGIKARP, 13, 17, 17), (179, 30, 82, 82)]))
    assert lead_level(emu) == 30                                    # the Magikarp no longer caps the gate (Route 3 grind loop)
    emu.memory.update(party_mem([(GYARADOS, 30, 82, 82), (179, 30, 82, 82)]))
    assert lead_level(emu) == 30
    assert lead_level(FakeEmulator(party_mem([(0x54, 9, 20, 20), (179, 30, 82, 82)]))) == 30  # weak lead first: still the team's 30


def test_trainee_band_level_is_only_for_the_team_ready_stage():
    from pokeagent.explorer.perceive import trainee_band_level
    emu = FakeEmulator(party_mem([(MAGIKARP, 13, 17, 17), (179, 30, 82, 82)]))
    assert trainee_band_level(emu) == min(30, 13 + TEAM_GAP) == 19


def test_trainee_slot_for_follows_the_magikarp_then_the_named_member():
    karp = FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0xB1, 18, 51, 51)]))
    assert trainee_slot_for(karp, 1) == 0 and trainee_slot_for(karp, None) == 0   # the Magikarp always wins
    weak = FakeEmulator(party_mem([(0xB1, 30, 79, 79), (0x54, 9, 20, 20)]))
    assert trainee_slot_for(weak, 1) == 1          # slot 1 is TEAM_GAP+ below the lead
    close = FakeEmulator(party_mem([(0xB1, 30, 79, 79), (0x54, 25, 60, 60)]))
    assert trainee_slot_for(close, 1) is None      # within the gap: already useful
    assert trainee_slot_for(weak, 0) is None       # the lead itself is never the trainee
    assert trainee_slot_for(weak, 2) is None       # out of range
    assert trainee_slot_for(weak, None) is None    # nobody named


# --- review blockers: team_ready training need, idle settle, true lead level, fighter trainee never flees -------------

def test_true_lead_level_is_the_strongest_healthy_member():
    from pokeagent.explorer.perceive import true_lead_level
    emu = FakeEmulator(party_mem([(MAGIKARP, 13, 17, 17), (179, 30, 82, 82)]))
    assert lead_level(emu) == 30 and true_lead_level(emu) == 30
    assert true_lead_level(FakeEmulator(party_mem([(0x54, 9, 20, 20), (179, 30, 82, 82)]))) == 30


def test_bandit_and_drill_key_by_the_true_level():
    from types import SimpleNamespace
    from pokeagent.bandit.points import wild_gap
    from pokeagent.grind.drill import _level
    emu = FakeEmulator({**party_mem([(MAGIKARP, 13, 17, 17), (179, 30, 82, 82)]), 0xCFF3: 10})
    ctx = SimpleNamespace(emu=emu)
    assert wild_gap(ctx) == 20 and _level(ctx) == 30


def _gy_ctx(level_pair=((MAGIKARP, 13, 17, 17), (179, 30, 82, 82))):
    from types import SimpleNamespace
    goals = {g: True for g in GOALS[:GOALS.index("team_ready")]}
    emu = FakeEmulator(party_mem(list(level_pair)))
    return goals, SimpleNamespace(emu=emu, step=0, battles=0, blackouts_row=0, grind=None, team_ready_idle=0,
                                  team_ready_skipped=False, team_plan=[], train_member=None,
                                  log=lambda *a, **k: None)


def _magikarp_action():
    from types import SimpleNamespace
    return SimpleNamespace(blocked="", member=SimpleNamespace(candidate=SimpleNamespace(source="magikarp")))


def test_team_ready_stage_asks_for_the_team_target_and_its_own_battle_budget():
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.explorer.grind import GRIND_BATTLES, GRIND_BATTLES_GYARADOS
    from pokeagent.magikarp import EVOLVE_LEVEL
    assert GRIND_BATTLES_GYARADOS == 120 and GRIND_BATTLES == 25
    goals, ctx = _gy_ctx()
    ctx.team_plan = [_magikarp_action()]
    assert PlanGoal._team_need(ctx, goals, 19) >= EVOLVE_LEVEL + TEAM_GAP == 26  # the plan's top action is the Magikarp
    ctx.team_plan = []
    assert PlanGoal._team_need(ctx, goals, 19) == 19                             # another action wins: no forced gate
    ctx.train_member = 0                                                          # ... unless the named trainee IS the Magikarp
    assert PlanGoal._team_need(ctx, goals, 19) >= 26
    ctx.train_member = None
    other = {g: True for g in GOALS[:GOALS.index("to_gym")]}
    assert PlanGoal._team_need(ctx, other, 19) == 19                             # another stage: untouched
    assert PlanGoal._budgeted(ctx, goals, 26, None) == 26
    ctx.step, ctx.battles = 300, GRIND_BATTLES + 5                              # past 25: the team_ready stage keeps training
    assert PlanGoal._budgeted(ctx, goals, 26, None) == 26
    ctx.step, ctx.battles = 600, GRIND_BATTLES_GYARADOS
    assert PlanGoal._budgeted(ctx, goals, 26, None) == 0


def test_other_stages_keep_the_25_battle_budget(monkeypatch):
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.explorer.grind import GRIND_BATTLES
    from pokeagent.knowledge import kb as kbmod
    monkeypatch.setattr(kbmod, "ROM_KB", None)
    _, ctx = _gy_ctx(((179, 8, 30, 30),))
    goals = {g: True for g in GOALS[:GOALS.index("to_gym") + 1]}
    assert PlanGoal._budgeted(ctx, goals, 12, None) == 12
    ctx.step, ctx.battles = 300, GRIND_BATTLES
    assert PlanGoal._budgeted(ctx, goals, 12, None) == 0


def test_team_ready_goal_settles_after_idle_closed_gate_steps_not_while_training():
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    from pokeagent.magikarp import GYARADOS_IDLE_CAP, GYARADOS_STEP_CAP
    assert GYARADOS_IDLE_CAP == 300 and GYARADOS_STEP_CAP == 6000
    _, ctx = _gy_ctx()
    for _ in range(GYARADOS_IDLE_CAP - 1):
        PlanGoal._team_ready_idle(ctx, False)
    assert not ctx.team_ready_skipped
    PlanGoal._team_ready_idle(ctx, True)                                         # training live: the count restarts
    assert ctx.team_ready_idle == 0
    for _ in range(GYARADOS_IDLE_CAP * 2):
        PlanGoal._team_ready_idle(ctx, True)
    assert not ctx.team_ready_skipped
    for _ in range(GYARADOS_IDLE_CAP):
        PlanGoal._team_ready_idle(ctx, False)
    assert ctx.team_ready_skipped


def test_team_ready_budget_does_not_leak_into_the_next_boss_stage():
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    _, ctx = _gy_ctx()
    tr = {g: True for g in GOALS[:GOALS.index("team_ready")]}
    assert PlanGoal._budgeted(ctx, tr, 26, None) == 26
    ctx.step, ctx.battles = 300, 30                                  # 30 flat battles at the team_ready stage
    assert PlanGoal._budgeted(ctx, tr, 26, None) == 26
    nxt = {g: True for g in GOALS[:GOALS.index("team_ready") + 1]}
    ctx.step, ctx.battles = 301, 31
    assert PlanGoal._budgeted(ctx, nxt, 26, None) == 26             # first step of the next stage: not pre-lifted
    assert not ctx.grind.lifted("rival_ss_anne") and not ctx.grind.lifted("team_ready")


def test_team_ready_idle_resets_on_a_level_gain():
    from pokeagent.explorer.behaviours.plan_goal import PlanGoal
    _, ctx = _gy_ctx()
    for _ in range(10):
        PlanGoal._team_ready_idle(ctx, False, 19)
    assert ctx.team_ready_idle == 9
    PlanGoal._team_ready_idle(ctx, False, 20)
    assert ctx.team_ready_idle == 0


def test_verdict_does_not_depend_on_party_order():
    """run explore-20261112-072650: swapping slots flipped 'raise X to L18' vs 'lead needs L27 (lead L9)'."""
    a, b = _mon("AQUA", 14), _mon("BLAZE", 9)
    fwd, rev = team_readiness([a, b], BOSS, "T", SYN), team_readiness([b, a], BOSS, "T", SYN)
    assert fwd.ready == rev.ready and fwd.lead.required == rev.lead.required
    assert fwd.lead.lead == rev.lead.lead == "AQUA"
    assert {(r.name, r.level, r.target) for r in fwd.members} == {(r.name, r.level, r.target) for r in rev.members}


def test_trainee_can_be_slot_zero_and_is_compared_to_the_strongest():
    from pokeagent.knowledge import team_plan
    weak, strong = _mon("BLAZE", 8), _mon("AQUA", 20)
    assert team_plan.trainee_slot([weak, strong], named=0) == 0     # slot 0 is the weakest: it is the trainee
    assert team_plan.trainee_slot([strong, weak], named=1) == 1     # same answer in either order
    assert team_plan.trainee_slot([_mon("BLAZE", 19), strong], named=0) is None   # within TEAM_GAP of the opener


def test_single_member_party_has_no_grind_pressure_from_breakers():
    from pokeagent.knowledge import team_plan
    solo = [_mon("AQUA", 15)]
    assert team_plan.grind_pressure(solo, 8, 0, 0, breakers=(0,), lead_level=15) == 0.0   # need met, only a catch helps
    duo = [_mon("AQUA", 15), _mon("BLAZE", 5)]
    assert team_plan.grind_pressure(duo, 8, 0, 0, breakers=(1,), lead_level=15) > 0.0     # a real second member still counts
