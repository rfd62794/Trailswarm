"""S.S. Anne blackout loop (2026-11-06): walk off the ship when unfit, route back to Vermilion after a blackout, leave the Mart
after buying, and never start a ship segment from a state whose blackout respawns behind Vermilion."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from pokeagent import checkpoint_goals as cg  # noqa: E402
from pokeagent.explorer import ship_gate as sg  # noqa: E402
from pokeagent.explorer.behaviours import Restock  # noqa: E402
from pokeagent.explorer.memory import MapMemory  # noqa: E402
from pokeagent.explorer.planner import plan_step  # noqa: E402
from pokeagent.explorer.world import WorldGraph  # noqa: E402
from pokeagent.goals import GOALS  # noqa: E402
import seg_store as ss  # noqa: E402
from test_team_inventory import make_ctx  # noqa: E402

DONE = {g: True for g in GOALS[:GOALS.index("ss_anne_2f") + 1]}
FIT = {**DONE, "_hp": (40, 40), "_level": 30, "_need": 25, "_train_level": 0, "_sprites": [], "_respawn": 0x05}


class FakeShipPlan:
    """The multi-floor ROM planner's interface: a fixed button list from anywhere aboard, the dock's exit warp as the goal."""

    def __init__(self, buttons):
        self.buttons, self.asked, self.tiles_asked = buttons, [], []

    def __call__(self, start, goals):
        self.asked.append((start, set(goals)))
        return list(self.buttons)

    def warp_tiles(self, m, dest=None):
        self.tiles_asked.append((m, dest))
        return {(m, 14, 0)}

    def follow(self, start, buttons):
        return [start, (0x61, 19, 3), (0x60, 2, 12)]


def test_under_level_on_the_ship_walks_off_once():
    plan, state = FakeShipPlan(["LEFT", "UP"]), {}
    goals = {**FIT, "_level": 12, "_ship": state, "_ship_plan": plan}
    step = plan_step(goals, {}, (0x61, 10, 3), "UP")
    assert step and step[0] == "LEFT" and "walk-off" in step[1] and state["off"] == 1, step
    assert plan.asked[0][1] == {(0x5E, 14, 0)}                      # the dock's exit to Vermilion is the goal
    assert plan_step(goals, {}, (0x05, 18, 31), "UP") is None       # off the ship: the walk-off ends
    assert state["off"] == 2
    assert plan_step(goals, {}, (0x61, 10, 3), "UP") is None        # once per run: aboard again, nothing pulls it off


def test_weak_lead_on_the_ship_also_walks_off_but_a_fit_one_does_not():
    plan = FakeShipPlan(["DOWN"])
    weak = {**FIT, "_hp": (6, 78), "_ship": {}, "_ship_plan": plan}
    assert plan_step(weak, {}, (0x63, 13, 6), "UP")[0] == "DOWN"
    fit = plan_step({**FIT, "_ship": {}, "_ship_plan": plan}, {}, (0x63, 13, 6), "UP")
    assert fit is None or "walk-off" not in fit[1], fit             # a fit lead is never walked off; the bow is no longer the goal, so it heads for the captain's door


def test_walk_off_presses_the_learned_edge_warp_instead_of_oscillating():
    plan = FakeShipPlan(["DOWN"])
    maps = {"99": {"warps": {"13,7,RIGHT": [97, 0, 3]}}}
    goals = {**FIT, "_hp": (6, 78), "_ship": {}, "_ship_plan": plan}
    step = plan_step(goals, maps, (0x63, 13, 7), "DOWN")
    assert step and step[0] == "RIGHT" and "learned warp" in step[1], step


def test_walk_off_is_capped():
    state = {"off": 1, "steps": sg.WALK_OFF_CAP}
    goals = {**FIT, "_level": 12, "_ship": state, "_ship_plan": FakeShipPlan(["UP"])}
    assert plan_step(goals, {}, (0x61, 10, 3), "UP") is None and state["off"] == 2


def _vermilion_maps(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    for x in range(3, 8):
        mem.visit(0x05, x, 10, 1)
    mem.m(0x05)["warps"]["7,10,UP"] = [0x59, 3, 7]
    mem.visit(0x59, 3, 7, 1)
    return mem.data["maps"]


def test_weak_in_vermilion_heals_even_when_the_respawn_is_already_vermilion(tmp_path):
    maps = _vermilion_maps(tmp_path)
    weak = {**FIT, "_hp": (6, 78), "to_vermilion": True}
    step = plan_step(weak, maps, (0x05, 3, 10), "UP")
    assert step and "checkpoint" in step[1], step
    assert plan_step({**FIT, "to_vermilion": True}, maps, (0x05, 3, 10), "UP") is None   # healthy and healed: no detour


def test_under_level_in_vermilion_goes_to_route6_to_grind_instead_of_boarding(tmp_path):
    maps = _vermilion_maps(tmp_path)
    maps["5"]["warps"]["4,10,UP"] = [0x11, 8, 35]
    mem = MapMemory(tmp_path / "m2.json")
    mem.visit(0x11, 8, 35, 1)
    maps["17"] = mem.data["maps"]["17"]
    goals = {**FIT, "_level": 12, "to_vermilion": True}
    step = plan_step(goals, maps, (0x05, 5, 10), "UP")
    assert step and step[0] == "LEFT" and "Route 6" in step[1], step
    assert plan_step({**goals, "_level": 30}, maps, (0x05, 5, 10), "UP") is None  # ready: the ship walk takes over


def _cerulean_to_vermilion(tmp_path, gap=False):
    mem = MapMemory(tmp_path / "maps.json")
    chain = [(0x03, 26, 35, 0x10), (0x10, 16, 1, 0x47), (0x47, 3, 4, 0x77), (0x77, 4, 4, 0x4A), (0x4A, 3, 4, 0x11), (0x11, 8, 35, 0x05)]
    for i, (m, x, y, dest) in enumerate(chain):
        ax, ay = (chain[i + 1][1], chain[i + 1][2] - 1) if i + 1 < len(chain) else (5, 6)   # arrival tile: beside the next hop
        mem.visit(m, x, y - 1, 1)
        mem.visit(m, x, y, 1)
        mem.m(m)["warps"][f"{x},{y},DOWN"] = [dest, ax, ay]
        mem.visit(dest, ax, ay, 1)
        if i + 1 < len(chain):
            mem.visit(dest, ax, ay + 1, 1)
    for x in range(20, 27):
        mem.visit(0x03, x, 34 if not gap else 20, 1)
    mem.visit(0x05, 5, 6, 1)
    return mem.data["maps"]


def test_route_back_from_cerulean_follows_the_learned_chain_to_vermilion(tmp_path):
    maps = _cerulean_to_vermilion(tmp_path)
    g = WorldGraph(maps)
    step = sg.route_back_step(g, FIT, (0x03, 24, 34))
    assert step and step[0] == "RIGHT" and "steps to Vermilion" in step[1], step
    # through the planner, with the stage a ship stage, from Cerulean
    step = plan_step({**FIT, "to_vermilion": True}, maps, (0x03, 24, 34), "UP")
    assert step and step[0] == "RIGHT" and "back to the ship" in step[1], step
    assert sg.route_back_step(g, FIT, (0x05, 5, 6)) is None  # in Vermilion: arrived


def test_route_back_goes_to_the_next_map_warp_when_the_learned_world_is_in_pieces(tmp_path):
    maps = _cerulean_to_vermilion(tmp_path, gap=True)
    g = WorldGraph(maps)
    assert sg.route_back_step(g, FIT, (0x03, 22, 20), lambda m: None) is None   # no path and no ROM grid: nothing better than exploring
    from pokeagent.legs import grid as G
    open_grid = G.from_ascii(["." * 40] * 36)
    step = sg.route_back_step(g, FIT, (0x03, 22, 20), lambda m: open_grid)      # the ROM par route to the seam warp
    assert step and step[0] in ("RIGHT", "DOWN") and "ROM route" in step[1], step


def test_restock_walks_out_of_the_mart_after_buying_and_does_not_hand_it_to_the_frontier(tmp_path, monkeypatch):
    from pokeagent.explorer import shop

    class Res:
        ok, reason, bought, money_before, money_after, bag_after = True, "ok", 10, 4000, 2000, {4: 11}

    monkeypatch.setattr(shop, "buy", lambda emu, item, qty: Res)
    ctx = make_ctx(tmp_path, 1, 4000, m=67, x=2, y=5)
    ctx.restock = {"intent": True}
    ctx.facing = "LEFT"
    Restock().step(ctx)                                  # the purchase
    assert ctx.restock["leave"] and not ctx.restock["intent"]
    d = Restock().step(ctx)
    assert d is not None and d.rule == "restock_leave" and d.button in ("RIGHT", "DOWN"), d
    ctx2 = make_ctx(tmp_path, 1, 4000, m=3, x=23, y=19)  # outside again: the leave flag clears, no restock loop
    ctx2.restock = ctx.restock
    assert Restock().step(ctx2) is None and not ctx2.restock["leave"] and not ctx2.restock["intent"]
    assert ctx2.restock["tries"] == 1                    # one purchase only


def _ck(root, name, respawn):
    d = root / "runs" / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.state"
    p.write_bytes(b"x")
    cg.write_completed(p, [], respawn)
    return p


def test_ckpt_prefers_a_ship_state_whose_respawn_is_ahead(tmp_path):
    best = _ck(tmp_path, "ss_anne_captain@63.best", 3)
    plain = _ck(tmp_path, "ss_anne_captain@63", 5)
    assert ss.ckpt(tmp_path, "ss_anne_captain@63") == plain                 # the best sits behind Vermilion: skipped
    best.with_name("ss_anne_captain@63.best.state").exists()
    only_behind = tmp_path / "o"
    _ck(only_behind, "ss_anne_captain@63", 3)
    assert ss.ckpt(only_behind, "ss_anne_captain@63").name == "ss_anne_captain@63.state"   # nothing better: still usable
    _ck(tmp_path, "to_route6.best", 3)
    assert ss.ckpt(tmp_path, "to_route6").name == "to_route6.best.state"    # only ship segments care


def test_unknown_respawn_is_not_behind(tmp_path):
    d = tmp_path / "runs" / "checkpoints"
    d.mkdir(parents=True)
    p = d / "ss_anne_captain@63.state"
    p.write_bytes(b"x")
    cg.write_completed(p, [])
    assert cg.read_respawn(p) is None and not cg.respawn_behind("ss_anne_captain@63", p)


def test_fit_and_aboard_takes_the_rom_route_to_the_captains_door_not_the_bow():
    """ROM: the bow (0x63) has only warps back to the deck; the captain's room (0x65) is entered from 2F (0x60). Stage targets
    pointing at the bow left 336 curriculum attempts parked there (frontier UP/DOWN beside the bow sailor)."""
    plan = FakeShipPlan(["UP", "LEFT"])
    goals = {**FIT, "_ship": {"off": 2}, "_ship_plan": plan}
    step = plan_step(goals, {}, (0x5F, 20, 6), "UP")
    assert step and step[0] == "UP" and "goal boarding" in step[1] and plan.tiles_asked[-1] == (0x60, 0x65), step
    assert plan.asked[-1][1] == {(0x60, 14, 0)}
    step = plan_step(goals, {}, (0x63, 11, 8), "UP")                     # parked at the bow: it is a dead end, route off it
    assert step and step[0] == "UP" and plan.tiles_asked[-1] == (0x60, 0x65), step
    assert plan_step(goals, {}, (0x65, 5, 2), "UP") is None              # inside the captain's room: its own dialog logic


def test_the_ship_stage_targets_the_captains_room_not_the_bow():
    from pokeagent.explorer import planner_east as pe
    for stage in ("rival_ss_anne", "ss_anne_captain"):
        assert pe.TARGETS[stage]((0x65, 5, 2)) and not pe.TARGETS[stage]((0x63, 11, 8)), stage


def test_fit_in_vermilion_walks_to_the_dock(tmp_path):
    maps = _vermilion_maps(tmp_path)
    maps["5"]["warps"]["5,10,DOWN"] = [0x5E, 14, 0]
    mem = MapMemory(tmp_path / "m3.json")
    mem.visit(0x5E, 14, 0, 1)
    maps["94"] = mem.data["maps"]["94"]
    step = plan_step({**FIT, "to_vermilion": True}, maps, (0x05, 3, 10), "UP")
    assert step and step[0] == "RIGHT" and "dock" in step[1], step


def test_route6_is_a_grind_spot_when_under_level_and_a_road_to_vermilion_when_ready(tmp_path):
    maps = _cerulean_to_vermilion(tmp_path)
    g = WorldGraph(maps)
    pos = (0x11, 8, 34)
    assert sg.route_back_step(g, {**FIT, "_level": 12}, pos) is None          # under-level: exploration grinds the grass
    step = sg.route_back_step(g, FIT, pos)
    assert step and "Vermilion" in step[1], step                              # ready: on to the ship
    assert sg.route_back_step(g, {**FIT, "_level": 12}, (0x03, 24, 34)) is not None   # from the Cerulean side it still walks east
