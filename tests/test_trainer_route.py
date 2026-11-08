"""trainer_route: next target on the route, engage / avoid / save / engage-forced, the routing-only
sight-line block that never blocks the only route, the _person_tile beaten-trainer extension, and the
trainer_hunt gates."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import trainer_ledger as T
from pokeagent.explorer import trainer_route as R
from pokeagent.explorer.behaviours.trainer_hunt import TRAINER_HUNT_STEP_CAP, TrainerHunt
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.stats import stat_value
from pokeagent.explorer.world import WorldGraph
from pokeagent.knowledge.party import Combatant
from test_item_balls import MAP, PX, PY, make_ctx

M = 35


def _mv(name, typ, power, acc=1.0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": 0, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc,
            "moves1": moves1}


# AQUA (WATER) sweeps ROCK/GROUND PEBBLE; BLAZE (FIRE) loses to it.
SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40), "3": _mv("EMBER", "FIRE", 40)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["FIRE", "ROCK", 0.5]],
    "species_by_dex": {"1": _species("AQUA", "WATER", "WATER", 60, 60, 65, 60, 60, ["TACKLE", "WATER GUN"]),
                       "2": _species("BLAZE", "FIRE", "FIRE", 44, 48, 65, 43, 50, ["TACKLE", "EMBER"]),
                       "3": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"])},
    "learnsets": {"AQUA": {"learnset": []}, "BLAZE": {"learnset": []}, "PEBBLE": {"learnset": []}},
}


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, (row["type1"],), hp, st, tuple(row["moves1"]), (8,) * 5, (0,) * 5)


STRONG = [_mon("AQUA", 30)]
WEAK = [_mon("BLAZE", 5)]

# Two on-route trainers (idx 0 at (11,20), idx 1 at (11,28)) and one off the map entirely (idx 2).
ROWS = [{"class": "BUG CATCHER", "party": 9, "x": 11, "y": 20, "mons": [(14, "PEBBLE")]},
        {"class": "LASS", "party": 8, "x": 11, "y": 28, "mons": [(14, "PEBBLE")]},
        {"class": "ROCKET", "party": 6, "x": 30, "y": 30, "mons": [(15, "PEBBLE")]}]


def _mem(tmp_path, bypass: bool) -> MapMemory:
    """Corridor x=11 y14..33 plus, when bypass, a loop out at x16 rejoining below the trainer's row."""
    mem = MapMemory(tmp_path / "maps.json")
    vis = mem.m(M)["visited"]
    for y in range(14, 34):
        vis[f"11,{y}"] = 1
    if bypass:
        for x in range(11, 17):
            vis[f"{x},15"] = vis[f"{x},25"] = 1
        for y in range(15, 26):
            vis[f"16,{y}"] = 1
    return mem


def _opts(mem, party, rows=ROWS, route_steps=19, player=(M, 11, 14)):
    led = T.TrainerLedger({M: rows})
    g = WorldGraph(mem.data["maps"])
    return led, R.options(led, M, player, g, route_steps, party, kb=SYN)


def test_next_target_is_the_nearest_unbeaten_engage_and_skips_beaten(tmp_path):
    mem = _mem(tmp_path, bypass=False)
    led, opts = _opts(mem, STRONG)
    t = R.next_target(opts)
    assert t.entry.idx == 0 and t.steps == 4 and t.entry.cls == "BUG CATCHER"
    led.mark_beaten(M, 0, "battle_log", 1)                       # beaten: never a target again
    opts = R.options(led, M, (M, 11, 14), WorldGraph(mem.data["maps"]), 19, STRONG, kb=SYN)
    assert opts[0].action == "ignore" and R.next_target(opts).entry.idx == 1
    assert opts[0].entry.x == 11 and opts[0].entry.y == 20      # but the tile still exists as a person


def test_engage_save_and_ignore_actions(tmp_path):
    mem = _mem(tmp_path, bypass=False)
    led, opts = _opts(mem, STRONG)
    assert opts[0].action == "engage" and "on the route" in opts[0].why
    assert opts[1].action == "engage"
    assert opts[2].action == "save"                             # wins but far off the route: save it
    # no party data to sim: unbeaten trainer is ignored, never engaged blind
    _, opts2 = _opts(mem, [], rows=ROWS[:1])
    assert opts2[0].action == "ignore" and opts2[0].margin is None


def test_avoid_when_thin_with_a_bypass_and_engage_forced_on_a_single_lane(tmp_path):
    # bypass loop exists: the sight line is temp-blocked and the goal still routes
    ctx = make_ctx(tmp_path, memory={MAP: M, PX: 11, PY: 14})
    ctx.mem = _mem(tmp_path, bypass=True)
    ctx.refresh()
    led, opts = _opts(ctx.mem, WEAK, rows=ROWS[:1])
    assert opts[0].action == "avoid" and opts[0].margin < R.ENGAGE_MARGIN
    assert R.block_sight(ctx, opts[0], lambda n: n == (M, 11, 33)) == "avoid"
    assert ctx.mem.temp_blocked                                  # the sight line is blocked now
    g = WorldGraph(ctx.mem.data["maps"])
    g.blocked_now = frozenset(ctx.mem.temp_blocked)
    assert g.path((M, 11, 14), lambda n: n == (M, 11, 33))       # the bypass carries the route
    # a single lane: nothing may be blocked, the decision is engage-forced
    ctx2 = make_ctx(tmp_path / "b", memory={MAP: M, PX: 11, PY: 14})
    ctx2.mem = _mem(tmp_path / "b", bypass=False)
    ctx2.refresh()
    led2, opts2 = _opts(ctx2.mem, WEAK, rows=ROWS[:1])
    assert R.block_sight(ctx2, opts2[0], lambda n: n == (M, 11, 33)) == "engage-forced"
    assert not ctx2.mem.temp_blocked                             # the only route was left open


def test_person_tile_extension_marks_a_beaten_trainers_tile(tmp_path):
    mem = _mem(tmp_path, bypass=False)
    mem.m(M)["npcs"] = {"slot7:pic4": {"pic": 4, "slot": 7, "positions": {"11,21": 1, "11,22": 1},
                                     "last": [11, 22], "moves": True}}  # it walked up: 'moves' is True
    mem.beaten_tiles = {(M, 11, 20)}
    assert mem._person_tile(M, 11, 20)                         # beaten placement + NPC recorded next to it
    assert not mem._person_tile(M, 11, 21)                     # the walked-to tile itself is not a placement
    mem2 = _mem(tmp_path / "c", bypass=False)
    mem2.beaten_tiles = {(M, 11, 20)}
    assert not mem2._person_tile(M, 11, 20)                    # no NPC there: the tile alone is not a person
    assert not mem._person_tile(M, 5, 5)                       # not a placement at all


def test_trainer_hunt_gates(tmp_path):
    ctx = make_ctx(tmp_path, memory={MAP: M, PX: 11, PY: 14})
    ctx.trainer_ledger = T.TrainerLedger({M: ROWS})
    ctx.refresh()
    hunt = TrainerHunt()
    assert hunt.applies(ctx)
    ctx.view.battling = True
    assert not hunt.applies(ctx)
    ctx.view.battling, ctx.view.box = False, True
    assert not hunt.applies(ctx)
    ctx.view.box = False
    ctx.proc = {"name": "p"}
    assert not hunt.applies(ctx)
    ctx.proc = None
    ctx.trainer_hunt_steps = TRAINER_HUNT_STEP_CAP + 1
    assert not hunt.applies(ctx)
    ctx.trainer_hunt_steps = 0
    led_all_beaten = T.TrainerLedger({M: ROWS})
    for i in range(len(ROWS)):
        led_all_beaten.mark_beaten(M, i, "flag", 1)
    ctx.trainer_ledger = led_all_beaten
    assert not hunt.applies(ctx)                               # every trainer beaten: nothing to hunt
