"""par_follow: follow the ROM par path on a synthetic grid; replan on sprites and failed presses; off = unchanged."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import par_follow as pf
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions, Frame
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.world import WorldGraph
from pokeagent.legs import grid as G

M = 5
# the learned graph zig-zags (BFS order DOWN then RIGHT...); the ROM par path is the straight row
ROWS = ["..........",
        ".#######..",
        "..........",
        "W........."]


def make(tmp_path, at=(0, 0), par_on=True, why="goal road north: 9 steps to map 0x0C"):
    emu = FakeEmulator({0xD35E: M, 0xD362: at[0], 0xD361: at[1]})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(par_follow=par_on), run_dir=tmp_path)
    ctx.par = pf.ParState(get=lambda m: G.from_ascii(ROWS) if m == M else None)
    ctx.view = Frame(M, at[0], at[1])
    ctx.mem.data["maps"][str(M)] = {"warps": {"9,0,RIGHT": [6, 1, 1]}}
    return ctx, why


def planned(ctx, buttons, why):
    """What plan_goal sees after plan_step: its press, with the BFS route recorded by WorldGraph."""
    pos = (ctx.view.m, ctx.view.x, ctx.view.y)
    WorldGraph.last_route = (pos, (6, 1, 1), buttons)
    return buttons[0], why


def test_follows_the_par_path_not_the_planner_zigzag(tmp_path):
    ctx, why = make(tmp_path)
    p, driver = pf.refine(ctx, planned(ctx, ["DOWN", "DOWN"] + ["RIGHT"] * 9 + ["UP", "UP", "RIGHT"], why), [])
    assert driver == "par" and p[0] == "RIGHT" and "par: 9 steps to (9,0)" in p[1]
    ctx.view = Frame(M, 3, 0)  # walked three tiles: the next press is still the straight row
    p, driver = pf.refine(ctx, planned(ctx, ["DOWN", "DOWN"] + ["RIGHT"] * 6 + ["UP", "UP", "RIGHT"], why), [])
    assert (p[0], driver) == ("RIGHT", "par")


def test_at_the_target_the_planners_leaving_press_stands(tmp_path):
    ctx, why = make(tmp_path, at=(9, 0))
    p, driver = pf.refine(ctx, planned(ctx, ["RIGHT"], why), [])
    assert driver == "" and p[0] == "RIGHT"


def test_replans_around_a_sprite_tile_and_never_presses_into_it(tmp_path):
    ctx, why = make(tmp_path, at=(2, 2), why="goal road north: 7 steps to map 0x0C")
    ctx.mem.data["maps"][str(M)]["warps"] = {"9,2,RIGHT": [6, 1, 1]}
    p, _ = pf.refine(ctx, planned(ctx, ["RIGHT"] * 8, why), [])
    assert p[0] == "RIGHT"
    ctx2, why = make(tmp_path, at=(2, 2))
    ctx2.mem.data["maps"][str(M)]["warps"] = {"9,2,RIGHT": [6, 1, 1]}
    p, driver = pf.refine(ctx2, planned(ctx2, ["RIGHT"] * 8, why), [(13, 3, 2)])   # a person on (3,2)
    assert driver == "par" and p[0] in ("DOWN",) and "par:" in p[1]               # row 1 is wall above: detour via row 3
    p, driver = pf.refine(ctx2, planned(ctx2, ["RIGHT"] * 8, why), [(13, 3, 2), (13, 2, 3), (13, 1, 2)])  # boxed in
    assert driver == "" and p[0] == "RIGHT"                                          # no par route: planner's press untouched


def test_temp_blocked_tile_is_routed_around(tmp_path):
    ctx, why = make(tmp_path, at=(2, 2))
    ctx.mem.data["maps"][str(M)]["warps"] = {"9,2,RIGHT": [6, 1, 1]}
    ctx.mem.temp_blocked[(M, 3, 2)] = ctx.frame + 100
    p, driver = pf.refine(ctx, planned(ctx, ["RIGHT"] * 8, why), [])
    assert driver == "par" and p[0] == "DOWN"


def test_replans_after_a_failed_press(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "MAX_FAILS", 2)
    ctx, why = make(tmp_path, at=(2, 2))
    ctx.mem.data["maps"][str(M)]["warps"] = {"9,2,RIGHT": [6, 1, 1]}
    p, _ = pf.refine(ctx, planned(ctx, ["RIGHT"] * 8, why), [])
    assert p[0] == "RIGHT"
    ctx.step += 1; ctx.last_press = "RIGHT"             # the press happened and the tile did not change
    p, driver = pf.refine(ctx, planned(ctx, ["RIGHT"] * 8, why), [])
    assert driver == "par" and p[0] == "DOWN" and (M, 3, 2) in ctx.par.blocked
    for _ in range(1):                         # repeated failures hand the leg back to the planner for a while
        ctx.step += 1; ctx.last_press = p[0]
        p, driver = pf.refine(ctx, planned(ctx, ["RIGHT"] * 8, why), [])
    assert driver == "" and ctx.par.cooldown_until > ctx.step


def test_a_phantom_warp_is_forgotten_not_walked_to(tmp_path):
    ctx, why = make(tmp_path, at=(2, 2))
    ctx.mem.data["maps"][str(M)]["warps"] = {"5,2,UP": [6, 1, 1]}   # (5,2) is open floor, not a ROM warp and not an edge
    p, driver = pf.refine(ctx, planned(ctx, ["RIGHT"] * 3 + ["UP"], why), [])
    assert driver == "" and "5,2,UP" not in ctx.mem.data["maps"][str(M)]["warps"]


def test_eligible_trip_is_explicit(tmp_path):
    ctx, _ = make(tmp_path)
    assert pf.eligible_trip(ctx, "HP 3/20: going home to Mom to heal (12 steps)") == "heal"
    assert pf.eligible_trip(ctx, "HP 3/20: to the Pokecenter to heal (30 steps)") == "heal"
    assert pf.eligible_trip(ctx, "goal road north: 14 steps to map 0x0C") == "goal"
    assert pf.eligible_trip(ctx, "goal leave the house: 6 steps to the door") == "goal"
    assert pf.eligible_trip(ctx, "goal road north: 9 steps to the northernmost known tile (3,4)") is None   # exploration
    assert pf.eligible_trip(ctx, "goal parcel: 5 steps to an unexplored door at (3,4)") is None
    assert pf.eligible_trip(ctx, "frontier: 4 steps to (1,2)") is None
    ctx.shop_intent = ("mart", 7)   # hook for the ball-buying builder
    assert pf.eligible_trip(ctx, "anything") == "mart"


def test_exploration_text_is_never_par_driven(tmp_path):
    ctx, _ = make(tmp_path)
    p, driver = pf.refine(ctx, planned(ctx, ["DOWN", "RIGHT"], "frontier: 4 steps to (1,2)"), [])
    assert driver == "" and p == ("DOWN", "frontier: 4 steps to (1,2)")


def test_flag_off_plan_goal_never_calls_par(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import plan_goal as pg
    called = []
    monkeypatch.setattr(pg.par_follow, "refine", lambda *a: called.append(1) or (("UP", "x"), "par"))
    monkeypatch.setattr(pg, "plan_step", lambda *a, **k: ("LEFT", "goal x: 3 steps to map 0x01"))
    ctx, _ = make(tmp_path, par_on=False)
    ctx.emu.set(0xD16C, 0)
    d = pg.PlanGoal().step(ctx)
    assert called == [] and (d.button, d.driver) == ("LEFT", "")
    ctx.opts.par_follow = True
    d = pg.PlanGoal().step(ctx)
    assert called and (d.button, d.driver) == ("UP", "par")


def test_decision_driver_reaches_the_decision_line(tmp_path):
    from pokeagent.explorer.decisions import make_record
    d = Decision("UP", "plan_goal", "w", driver="par")
    assert d.driver == "par" and Decision("UP", "r").driver == ""


def test_training_is_not_an_eligible_trip(tmp_path):
    ctx, _ = make(tmp_path)
    ctx.emu.set(0xD18C, 5)   # lead level (wPartyMon1Level)
    ctx.train_need = 12
    from pokeagent.explorer.perceive import lead_level
    assert lead_level(ctx.emu) == 5 and pf.training(ctx)
    assert pf.eligible_trip(ctx, "goal road north: 14 steps to map 0x0C") is None
    assert pf.eligible_trip(ctx, "HP 3/20: to the Pokecenter to heal (30 steps)") == "heal"   # a heal trip is still a trip
    ctx.train_need = 0   # budget spent / bandit skipped the grind
    assert pf.eligible_trip(ctx, "goal road north: 14 steps to map 0x0C") == "goal"


def test_a_relearned_phantom_warp_is_forgotten_again_and_then_tombstoned(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    key = "9,11,UP"
    for cycle in range(2):
        mem.m(0)["warps"][key] = [40, 5, 11]          # (re)learned, e.g. merged back from another agent's memory
        mem._note_warp_disproof(0, key); mem._note_warp_disproof(0, key)
        assert key not in mem.m(0)["warps"]
    assert "0:" + key in mem.data["bad_warps"]
