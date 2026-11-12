"""The Magikarp money reserve: the floor that protects the 500 yen, and the deferred-goal circle-back."""
from __future__ import annotations

from pokeagent import magikarp_reserve
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import magikarp_deferral
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.economy import budget, shopping
from pokeagent.explorer.economy.bundles import candidate_bundles
from pokeagent.explorer.economy.prices import POKE_BALL
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.planner_magikarp import magikarp_step
from pokeagent.explorer.world import WorldGraph
from pokeagent.goals import check_goals
from pokeagent.knowledge.catch_plan import plan_catches
from pokeagent.magikarp import BUY_STEP_CAP, MAGIKARP_PRICE, MT_MOON_CENTER, magikarp_goal_settled
from test_catch_plan import _plan
from test_magikarp import STARTER, bcd, party_mem

MAP, PX, PY = 0xD35E, 0xD362, 0xD361
PARTY = [[1, 10, 0, 30, 30]]   # shopping_list's party-row shape (test_economy.PARTY)
FLOOR = MAGIKARP_PRICE + magikarp_reserve.MAGIKARP_RESERVE_MARGIN   # 600


def mk_ctx(tmp_path, *, mons=None, m=MT_MOON_CENTER, x=5, y=5, money=120, maps=None) -> ExplorerContext:
    emu = FakeEmulator({**party_mem(mons or [(STARTER, 18, 51, 51)]), **bcd(money), MAP: m, PX: x, PY: y})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=20, train_need=99)
    if maps is not None:
        ctx.mem.data["maps"] = maps
    ctx.refresh()
    return ctx


def r4_maps() -> dict:
    """Route 4 (15): the visited column down to the Mt Moon Pokemon Center door, warp into 0x44 (68)."""
    return {"15": {"visited": {f"11,{y}": 1 for y in (6, 7, 8)}, "blocked": [], "warps": {"11,6,UP": [68, 3, 7]}}}


def lst(money):
    return shopping.shopping_list({}, {}, money, PARTY, None, needs_balls=True, cave=False)


# --- the floor ---------------------------------------------------------------------------------------------------

def test_magikarp_floor():
    assert magikarp_reserve.magikarp_floor({}, {0x02}) == FLOOR                    # Pewter seen, goal live
    assert magikarp_reserve.magikarp_floor({"had_magikarp": True}, {0x02}) == 0    # owned: settled
    assert magikarp_reserve.magikarp_floor({"buy_skipped": True}, {0x02}) == 0     # skipped: settled
    assert magikarp_reserve.magikarp_floor({}, {0x02, 0x3B}) == 0                  # Mt Moon 1F seen: settled
    assert magikarp_reserve.magikarp_floor({}, set()) == 0                         # before Pewter
    assert magikarp_reserve.magikarp_floor({}, {0x0D, 0x33}) == 0                  # Route 2 / Forest, Pewter unreached


def test_reserve_blocks_the_buy_that_would_cross_below_the_floor():
    budget.set_magikarp_floor(magikarp_reserve.magikarp_floor({}, {0x02}))
    assert budget.magikarp_floor() == FLOOR
    buy = lst(700)
    assert not buy or 700 - shopping.cost(buy) >= FLOOR     # nothing takes the balance below 600
    budget.set_magikarp_floor(0)
    assert (POKE_BALL, 1) in lst(700) and 700 - shopping.cost(lst(700)) < FLOOR   # floor 0: the old buy returns


def test_the_floor_lifts_once_the_goal_settles_and_buys_again():
    for st, seen in [({"had_magikarp": True}, {0x02}), ({"buy_skipped": True}, {0x02}), ({}, {0x02, 0x3B})]:
        budget.set_magikarp_floor(magikarp_reserve.magikarp_floor(st, seen))
        assert budget.magikarp_floor() == 0 and (POKE_BALL, 1) in lst(700)


def test_floor_comes_through_budget_and_reaches_the_plain_dict_callers():
    budget.set_magikarp_floor(FLOOR)
    assert budget.spendable({}, 800) == 200
    budget.set_magikarp_floor(0)
    assert budget.spendable({}, 800) == 300     # the old formula, untouched
    budget.set_magikarp_floor(FLOOR)
    bundles = candidate_bundles({}, {}, 700, PARTY, None, needs_balls=True, cave=False)
    assert all(700 - shopping.cost(list(b.items)) >= FLOOR for b in bundles)  # no bundle dips under 600
    plan = _plan(balls=0, money=700)                                          # plain goals dict, as callers pass
    assert plan and all(a.balls == 0 for a in plan)                           # catch_plan: no ball buys either
    budget.set_magikarp_floor(0)
    assert any(a.balls for a in _plan(balls=0, money=700))                    # floor 0: balls planned again


def test_check_goals_is_a_pure_bool_ladder():
    emu = FakeEmulator({**party_mem([(STARTER, 18, 51, 51)]), **bcd(700), MAP: 0x0E})
    g = check_goals(emu, {})
    assert g and not any(k.startswith("_") for k in g) and all(isinstance(v, bool) for v in g.values())


# --- the deferral latch ------------------------------------------------------------------------------------------

def test_poor_at_the_center_defers_and_a_full_party_still_skips(tmp_path):
    ctx = mk_ctx(tmp_path, money=120)                       # poor with a free slot
    assert not ctx.goals()["buy_magikarp"] and ctx.get("buy_deferred") and not ctx.buy_skipped
    full = mk_ctx(tmp_path, money=120, mons=[(STARTER, 18, 51, 51)] * 6)
    assert full.goals()["buy_magikarp"] and full.buy_skipped and not full.get("buy_deferred")


def test_deferral_clears_the_center_intent(tmp_path):
    from pokeagent.explorer.behaviours import PlanGoal
    ctx = mk_ctx(tmp_path, money=120)
    ctx.center_intent = "buy_magikarp"
    PlanGoal().step(ctx)
    assert ctx.get("buy_deferred") and ctx.center_intent is None      # deferred: the planner must walk out and earn


def test_deferred_goal_keeps_the_planner_off_the_salesman():
    goals = {"buy_magikarp": False, "_buy_deferred": True}
    assert magikarp_step(WorldGraph({}), {}, goals, (0x0F, 11, 8), "UP") is None
    assert magikarp_deferral.deferred(type("C", (), {"get": lambda s, k, d=None: True})())


def test_deferred_goal_keeps_the_generic_planner_out_of_the_center():
    """Review of d0a9166: magikarp_step's None fell through to east_road_step's g.path(pos, _on(0x44)) - door ping-pong."""
    from pokeagent.explorer.planner_east import LADDER, east_road_step

    class Everywhere(WorldGraph):                      # every target is one step away
        def path(self, *a, **k):
            return ["UP"]

    done = {s: True for s in LADDER[:LADDER.index("buy_magikarp")]}
    poor = east_road_step(Everywhere({}), {}, {**done, "_buy_deferred": True, "_level": 20, "_train_level": 8}, (0x0F, 11, 8))
    assert poor is None or "Mt Moon Pokemon Center" not in poor[1] and "toward it" not in poor[1]
    rich = east_road_step(Everywhere({}), {}, {**done, "_level": 20, "_train_level": 8}, (0x0F, 11, 8))
    assert rich is not None                            # not deferred: the goal still walks to the center


# --- the counters ------------------------------------------------------------------------------------------------

def test_tick_counts_once_per_plan_step(tmp_path):
    from pokeagent.explorer.behaviours import PlanGoal
    rich = mk_ctx(tmp_path, money=3000)                     # the active attempt at 0x44
    PlanGoal().step(rich)
    assert rich.buy_steps == 1 and rich.get("deferred_steps", 0) == 0
    poor = mk_ctx(tmp_path, money=120)                      # deferred from the first tick
    PlanGoal().step(poor)
    assert poor.get("deferred_steps") == 1 and poor.buy_steps == 0


def test_buy_steps_pause_while_deferred_and_restart_once_the_trip_begins(tmp_path):
    ctx = mk_ctx(tmp_path, money=120, m=0x0F, x=11, y=8, maps=r4_maps())
    ctx["buy_deferred"] = True
    for _ in range(BUY_STEP_CAP + 50):
        magikarp_deferral.tick(ctx, 0x0F)                   # >600 deferred steps on Route 4: no buy_skipped
    assert not ctx.buy_skipped and ctx.buy_steps == 0 and ctx.get("deferred_steps") == BUY_STEP_CAP + 50
    ctx.emu.memory.update(bcd(700))                         # money restored, the door 3 steps away
    magikarp_deferral.tick(ctx, 0x0F)
    assert not ctx.get("buy_deferred") and ctx.buy_steps == 0    # circle-back: the attempt restarts fresh
    magikarp_deferral.tick(ctx, 0x0F)
    assert ctx.buy_steps == 1                                    # and counts again with its own cap


def test_deferred_steps_cap_settles_skipped(tmp_path):
    ctx = mk_ctx(tmp_path, money=120, m=0x0F, x=11, y=8)
    ctx["buy_deferred"] = True
    for _ in range(magikarp_reserve.CIRCLE_BACK_STEP_CAP):
        magikarp_deferral.tick(ctx, 0x0F)
    assert not ctx.buy_skipped
    magikarp_deferral.tick(ctx, 0x0F)
    assert ctx.buy_skipped and ctx.goals()["buy_magikarp"]       # settled for the run, never re-opens
    step = ctx.get("deferred_steps")
    magikarp_deferral.tick(ctx, 0x0F)
    assert ctx.get("deferred_steps") == step                     # settled: the counter stops too


# --- circle-back -------------------------------------------------------------------------------------------------

def test_should_circle_back():
    assert magikarp_reserve.should_circle_back(700, 3, 0x0E, 40)
    assert not magikarp_reserve.should_circle_back(550, 3, 0x0E, 40)     # under price + margin
    assert not magikarp_reserve.should_circle_back(700, 3, 0x0E, 81)     # past the path bound
    assert not magikarp_reserve.should_circle_back(700, 6, 0x0E, 40)     # no party slot
    assert not magikarp_reserve.should_circle_back(700, 3, 0x0E, None)   # no learned route
    assert not magikarp_reserve.should_circle_back(700, 3, 0x03, 40)     # Cerulean: east of Mt Moon
    assert magikarp_reserve.should_circle_back(700, 3, MT_MOON_CENTER, 0)  # inside already (a heal), rich


def test_circle_back_inside_tick(tmp_path):
    ctx = mk_ctx(tmp_path, money=700, m=0x0F, x=11, y=8, maps=r4_maps())
    ctx["buy_deferred"] = True
    magikarp_deferral.tick(ctx, 0x0F)
    assert not ctx.get("buy_deferred") and ctx.buy_steps == 0    # all four conditions: the trip begins
    ctx = mk_ctx(tmp_path, money=550, m=0x0F, x=11, y=8, maps=r4_maps())
    ctx["buy_deferred"] = True
    magikarp_deferral.tick(ctx, 0x0F)
    assert ctx.get("buy_deferred")                               # short of 600: still waiting


def test_mt_moon_1f_settles_even_while_deferred():
    st = {"buy_deferred": True}
    emu = FakeEmulator({**party_mem([(STARTER, 18, 51, 51)]), **bcd(120), MAP: 0x3B})
    assert magikarp_goal_settled(emu, st, {0x3B, MT_MOON_CENTER})        # the cave settles the goal for good
    assert not magikarp_reserve.should_circle_back(700, 3, 0x3B, 5)      # never once the cave is entered
    plan_catches([], 1, {}, 0, 0, 0, [], {}, [], 10)                     # sanity: empty plan needs no money path
