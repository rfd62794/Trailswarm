"""cut_learner: the learner goal's settled detector, the step cap, the pick_target table maths, learner_hunt."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokeagent import campaign, goals
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import catch_list
from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.explorer.behaviours.learner_hunt import LearnerHunt
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.goals import GOALS, check_goals
from pokeagent.knowledge import kb as kbmod
from pokeagent.knowledge.cut_learner import LEARNER_STEP_CAP, cut_capable, party_names, pick_target

SQUIRTLE, MAGIKARP, ODDISH = 0xB1, 0x85, 0xB9          # internal species ids (kb name_of_internal)
HM = {"cut": {"BULBASAUR", "CHARMANDER", "ODDISH", "PARAS", "BELLSPROUT", "SANDSHREW", "TENTACOOL", "KRABBY", "KINGLER"}}
ROM = {"name_of_internal": {str(SQUIRTLE): "SQUIRTLE", str(MAGIKARP): "MAGIKARP", str(ODDISH): "ODDISH"}}

# The Red grass tables (kb/rom_tables.json shape; section 2 of the directive): Route 6's ODDISH slots give 89/256 = .348.
WILD = {
    16: {"grass_rate": 15, "grass": [[13, "ODDISH"], [13, "PIDGEY"], [15, "PIDGEY"], [10, "MANKEY"], [12, "MANKEY"],
                                     [15, "ODDISH"], [16, "ODDISH"], [16, "PIDGEY"], [14, "MANKEY"], [16, "MANKEY"]]},
    17: {"grass_rate": 15, "grass": [[13, "ODDISH"], [13, "PIDGEY"], [15, "PIDGEY"], [10, "MANKEY"], [12, "MANKEY"],
                                     [15, "ODDISH"], [16, "PIDGEY"], [16, "ODDISH"], [14, "MANKEY"], [16, "MANKEY"]],
         "water_rate": 10, "water": [[15, "TENTACOOL"]] * 10},
    18: {"grass_rate": 15, "grass": [[19, "PIDGEY"], [19, "ODDISH"], [17, "MANKEY"], [22, "ODDISH"], [22, "PIDGEY"],
                                     [18, "MANKEY"], [18, "GROWLITHE"], [20, "GROWLITHE"], [19, "MANKEY"], [20, "MANKEY"]]},
    22: {"grass_rate": 15, "grass": [[14, "EKANS"], [15, "SPEAROW"], [12, "EKANS"], [9, "DROWZEE"], [13, "SPEAROW"],
                                     [13, "DROWZEE"], [15, "EKANS"], [17, "SPEAROW"], [11, "DROWZEE"], [15, "DROWZEE"]]},
    35: {"grass_rate": 25, "grass": [[7, "WEEDLE"], [8, "KAKUNA"], [12, "PIDGEY"], [12, "ODDISH"], [13, "ODDISH"],
                                     [10, "ABRA"], [14, "ODDISH"], [13, "PIDGEY"], [8, "ABRA"], [12, "ABRA"]]},
    36: {"grass_rate": 15, "grass": [[8, "WEEDLE"], [9, "KAKUNA"], [13, "PIDGEY"], [12, "ODDISH"], [13, "ODDISH"],
                                     [12, "ABRA"], [14, "ODDISH"], [10, "ABRA"], [7, "METAPOD"], [8, "CATERPIE"]]},
    153: {"water_rate": 10, "water": [[25, "KINGLER"]] * 10},  # a water-only Cut species: never a grass candidate
}

# Map hops over the learned graph from Vermilion (Route 6 sits on its north edge; Route 5 is the detour the
# default abs-id distance misjudges: |0x10-5| < |0x11-5| although Route 6 is the adjacent map).
HOPS = {16: 5, 17: 1, 18: 6, 22: 1, 35: 8, 36: 9}
DIST = lambda a, b: HOPS.get(b, 99)


def test_pick_target_picks_the_nearest_known_grass_map():
    t = pick_target(5, {16, 17}, HM, WILD, distance=DIST)
    assert t is not None and (t.map, t.name, t.species, t.levels, t.rate) == (0x11, "Route 6", "ODDISH", (13, 16), 15)
    assert abs(t.chance - 0.348) < 0.01
    assert pick_target(5, {35}, HM, WILD).map == 0x23            # only Route 24 is known: it wins
    assert pick_target(5, {22}, HM, {22: WILD[22]}) is None       # Route 11 alone holds no Cut species
    assert pick_target(5, {16, 17}, HM, {}) is None               # empty tables: no candidate
    assert pick_target(5, {153}, HM, {153: WILD[153]}) is None    # water-only Cut species: never chosen
    assert pick_target(5, {153, 17}, HM, WILD, distance=DIST).species == "ODDISH"  # grass only, not the Tentacool


def test_cut_capable_and_party_names():
    assert not cut_capable(["SQUIRTLE", "MAGIKARP"], HM)
    assert cut_capable(["SQUIRTLE", "MAGIKARP", "ODDISH"], HM)
    assert not cut_capable(["ODDISH"], None) and not cut_capable(["ODDISH"], {})
    emu = FakeEmulator({0xD163: 2, 0xD164: SQUIRTLE, 0xD165: MAGIKARP})
    assert party_names(emu, ROM) == ["SQUIRTLE", "MAGIKARP"] and party_names(emu, None) is None


def _squirtle_magikarp():
    return FakeEmulator({0xD35E: 5, 0xD803: 1, 0xD163: 2, 0xD164: SQUIRTLE, 0xD165: MAGIKARP})  # hm01_cut's flag set


def test_goal_order_and_settled_detector(monkeypatch):
    i = GOALS.index("hm01_cut")
    assert GOALS[i:i + 4] == ["hm01_cut", "cut_learner", "cut_taught", "pokemon_fan_club"]
    monkeypatch.setattr(kbmod, "ROM_KB", ROM)
    monkeypatch.setattr(catch_list, "hm_table", lambda: {"cut": frozenset(HM["cut"])})
    emu, st = _squirtle_magikarp(), {}
    assert check_goals(emu, st)["hm01_cut"] and not check_goals(emu, st)["cut_learner"]   # nobody can learn it yet
    emu.memory.update({0xD163: 3, 0xD166: ODDISH})
    assert check_goals(emu, st)["cut_learner"]                                           # Oddish joins: settled
    emu.set(0xD163, 2)
    assert check_goals(emu, st)["cut_learner"]                                           # sticky: stays settled
    emu2 = FakeEmulator({0xD803: 1, 0xD163: 1, 0xD164: SQUIRTLE, 0xD173: 15})
    assert check_goals(emu2, {})["cut_learner"]                                          # the party knows CUT
    monkeypatch.setattr(catch_list, "hm_table", lambda: {})
    assert check_goals(_squirtle_magikarp(), {})["cut_learner"]                          # no table: never blocks


def _stage_ctx(tmp_path, mons):
    mem = {0xD35E: 0x11, 0xD362: 13, 0xD361: 6, 0xD803: 1, 0xD163: len(mons)}
    for i, sp in enumerate(mons):
        mem[0xD164 + i] = sp
    ctx = ExplorerContext(emu=FakeEmulator(mem), mem=MapMemory(tmp_path / "maps.json"),
                          opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=20)
    ctx.mem.m(0x11)
    ctx.refresh()
    return ctx


def test_learner_stage_step_cap_settles_the_goal(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import PlanGoal
    monkeypatch.setattr(kbmod, "ROM_KB", ROM)
    monkeypatch.setattr(catch_list, "hm_table", lambda: {"cut": frozenset(HM["cut"])})
    ctx = _stage_ctx(tmp_path, [SQUIRTLE, MAGIKARP])
    assert not ctx.goals()["cut_learner"]
    ctx.cut_learner_steps = LEARNER_STEP_CAP - 1
    PlanGoal().step(ctx)
    assert ctx.cut_learner_steps == LEARNER_STEP_CAP and not ctx.cut_learner_skipped and not ctx.goals()["cut_learner"]
    PlanGoal().step(ctx)
    assert ctx.cut_learner_skipped and ctx.goals()["cut_learner"]                        # past the cap: settled


def _beh_ctx(goals, battling=False, box=False, skipped=False):
    return SimpleNamespace(goals=lambda: goals, view=SimpleNamespace(m=5, x=4, y=3, battling=battling, box=box),
                           proc=None, cut_learner_skipped=skipped, hunt_grass=True, learner_target=None,
                           mem=SimpleNamespace(data={"maps": {}}, temp_blocked=set()), log=lambda *a, **k: None)


def test_learner_hunt_applies_only_on_the_open_stage():
    h = LearnerHunt()
    assert not h.applies(_beh_ctx({"hm01_cut": False, "cut_learner": False}))            # before hm01_cut
    c = _beh_ctx({"hm01_cut": True, "cut_learner": False})
    assert h.applies(c) and not c.hunt_grass                                            # open stage; the flag self-clears
    assert not h.applies(_beh_ctx({"hm01_cut": True, "cut_learner": True}))             # settled
    assert not h.applies(_beh_ctx({"hm01_cut": True, "cut_learner": False}, battling=True))
    assert not h.applies(_beh_ctx({"hm01_cut": True, "cut_learner": False}, box=True))
    assert not h.applies(_beh_ctx({"hm01_cut": True, "cut_learner": False}, skipped=True))
    names = [b.name for b in default_behaviours()]
    assert names.index("plan_goal") < names.index("learner_hunt") < names.index("frontier")


def test_catch_target_map_only_while_cut_is_an_uncovered_need():
    done = {g: True for g in GOALS}
    done["vermilion_gym_entry"] = done["beat_surge"] = False                           # upcoming: cut, puzzle, ...
    t = catch_list.catch_target_map(done, ["SQUIRTLE"], HM, WILD, 5, {35})
    assert t is not None and t.map == 0x23
    assert catch_list.catch_target_map(done, ["ODDISH"], HM, WILD, 5, {35}) is None    # the party covers cut -> puzzle is first
    assert catch_list.catch_target_map({g: True for g in GOALS}, ["SQUIRTLE"], HM, WILD, 5, {35}) is None


BULBASAUR = 0x99


def test_cut_learner_needs_hm01_in_hand(monkeypatch):
    """A Cut-capable starter must not settle cut_learner in Pallet Town: the goal sits behind hm01_cut."""
    monkeypatch.setattr(kbmod, "ROM_KB", {"name_of_internal": {str(BULBASAUR): "BULBASAUR", str(SQUIRTLE): "SQUIRTLE"}})
    monkeypatch.setattr(catch_list, "hm_table", lambda: {"cut": frozenset(HM["cut"])})
    emu, st = FakeEmulator({0xD35E: 0x0C, 0xD163: 1, 0xD164: BULBASAUR}), {}
    assert not check_goals(emu, st)["hm01_cut"] and not check_goals(emu, st)["cut_learner"]
    assert not st.get("had_cut_learner")                                                # no sticky flag set early
    emu.set(0xD803, 1)
    assert check_goals(emu, st)["cut_learner"]                                          # HM01 in hand: learner present
    sq = FakeEmulator({0xD35E: 5, 0xD803: 1, 0xD163: 1, 0xD164: SQUIRTLE})
    sst = {}
    assert not check_goals(sq, sst)["cut_learner"]                                      # no learner yet
    sst["cut_learner_skipped"] = True
    assert check_goals(sq, sst)["cut_learner"]                                          # settled by the cap


def test_frontier_does_not_hunt_grass_when_weak(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import frontier
    seen = {}
    monkeypatch.setattr(frontier, "_memory_step", lambda ctx, m, x, y, **kw: (seen.update(kw) or ("Up", "t")))
    ctx = _stage_ctx(tmp_path, [SQUIRTLE])
    ctx.hunt_grass = True
    ctx.emu.memory.update({0xD16C: 0, 0xD16D: 5, 0xD18D: 0, 0xD18E: 20})              # 5/20 HP: weak
    frontier.Frontier().step(ctx)
    assert seen["grass"] == "avoid"
    ctx.emu.memory.update({0xD16D: 20})
    frontier.Frontier().step(ctx)
    assert seen["grass"] == "seek"


def test_learner_hunt_repicks_when_target_unreachable(monkeypatch):
    from pokeagent.explorer.behaviours import learner_hunt as lh
    a = SimpleNamespace(map=0x10, name="A", species="ODDISH", levels=(5, 6), chance=.3, rate=15)
    b = SimpleNamespace(map=0x11, name="B", species="ODDISH", levels=(5, 6), chance=.3, rate=15)
    picks = iter([a, b])

    class G:
        blocked_now = frozenset()
        def __init__(self, *_a): pass
        def path(self, _start, goal):
            return ["Up", "Up"] if goal((0x11, 0, 0)) else None                         # only B is reachable

    monkeypatch.setattr(lh, "WorldGraph", G)
    monkeypatch.setattr(lh, "catch_target_map", lambda *a, **k: next(picks))
    monkeypatch.setattr(lh, "our_party", lambda emu: [])
    monkeypatch.setattr(lh, "hm_table", lambda: {})
    monkeypatch.setattr(lh, "table", lambda *a: {})
    ctx = _beh_ctx({"hm01_cut": True, "cut_learner": False})
    ctx.emu = None
    d = LearnerHunt().step(ctx)
    assert ctx.learner_target is b and d is not None and d.button == "Up"
