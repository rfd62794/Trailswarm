"""Item balls: pic-61 sprite detection, the pickup behaviour's gates and detour budget,
item-text parsing, the '*' legend kind, and the maps[m]["items"] world facts (Item_Balls_Directive)."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import items, legend, tilekind
from pokeagent.explorer.behaviours.pickup import PICKUP_DETOUR, Pickup
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import ascii_vision
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.press_interact import record_interaction

TM = 0xC3A0
MAP, PX, PY, PARTY = 0xD35E, 0xD362, 0xD361, 0xD163


def ball_sprite(emu, slot: int, x: int, y: int, pic: int = 61, moving: int = 0) -> None:
    """A sprite-table slot: pic at 0xC1x0, movement status at +1, map pos (x+4, y+4) at 0xC2x4/5."""
    emu.set(0xC100 + 16 * slot, pic)
    emu.set(0xC101 + 16 * slot, moving)
    emu.set(0xC204 + 16 * slot, y + 4)
    emu.set(0xC205 + 16 * slot, x + 4)


def corridor(mem, m: int, y: int, xs) -> None:
    """A straight visited corridor so WorldGraph BFS can route along row y."""
    mem.m(m)["visited"].update({f"{x},{y}": 1 for x in xs})


def make_ctx(tmp_path, memory=None, **fields):
    emu = FakeEmulator(memory or {})
    mem = MapMemory(tmp_path / "maps.json")
    return ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path,
                           stable_frames=10, **fields)


def applies(ctx) -> bool:
    ctx.refresh()
    return Pickup().applies(ctx)


# --- items.py: live sprite-table detection ---------------------------------

def test_item_balls_finds_static_pic61_and_ignores_moving_hidden_and_other():
    emu = FakeEmulator()
    ball_sprite(emu, 1, 10, 20)                    # a real item ball
    ball_sprite(emu, 2, 30, 30, moving=0x10)       # pic 61 but a movement in progress
    emu.set(0xC130, 61); emu.set(0xC131, 0)        # pic 61 but no map position (raw 0 -> -4,-4)
    ball_sprite(emu, 4, 15, 15, pic=7)             # an ordinary NPC
    ball_sprite(emu, 5, 40, 40)                    # a second real item ball
    ball_sprite(emu, 15, 50, 50)                   # the last slot counts too
    assert items.item_balls(emu) == [(1, 10, 20), (5, 40, 40), (15, 50, 50)]


def test_is_item_ball_needs_pic61_and_never_moved():
    assert items.is_item_ball({"pic": 61, "moves": False})
    assert not items.is_item_ball({"pic": 61, "moves": True})
    assert not items.is_item_ball({"pic": 7, "moves": False})
    assert not items.is_item_ball(None) and not items.is_item_ball({})


def test_parse_item_text_found_and_obtained():
    assert items.parse_item_text("BCN found POTION!") == "POTION"
    assert items.parse_item_text("PLAYER obtained SUPER POTION!") == "SUPER POTION"
    assert items.parse_item_text("It's a POKe BALL!") is None
    assert items.parse_item_text("") is None and items.parse_item_text(None) is None


# --- MapMemory items records -------------------------------------------------

def test_note_item_ball_records_world_fact_and_counts_picked_once_per_run(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    mem.note_item_ball(13, 10, 5, text="It's a POKe BALL!", seen=True)
    mem.note_item_ball(13, 10, 5, text="BCN found POTION!", seen=False)  # the close with the full dialog
    e = mem.m(13)["items"]["10,5"]
    assert e["pic"] == 61 and e["item"] == "POTION" and e["seen"] == 1 and e["picked"] == 1
    mem.note_item_ball(13, 10, 5, text="BCN found POTION!", seen=False)  # same run: not counted twice
    assert mem.m(13)["items"]["10,5"]["picked"] == 1
    # a fresh MapMemory is a new run: the same pickup counts again
    mem2 = MapMemory(tmp_path / "maps.json")
    mem2.data = mem.data
    mem2.note_item_ball(13, 10, 5, text="BCN found POTION!", seen=False)
    assert mem2.m(13)["items"]["10,5"]["picked"] == 2


def test_interact_facing_a_ball_records_items(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    mem.m(13).setdefault("npcs", {})["slot1:pic61"] = {
        "pic": 61, "slot": 1, "positions": {"10,5": 1}, "last": [10, 5], "text": "", "talked": 0, "moves": False}
    mem.interact(13, 9, 5, "RIGHT", "found POTION!")
    e = mem.m(13)["items"]["10,5"]
    assert e["seen"] == 1 and e["item"] == "POTION" and e["picked"] == 1
    # facing somewhere else records nothing
    mem.interact(13, 9, 5, "LEFT", "nothing")
    assert list(mem.m(13)["items"]) == ["10,5"]


def test_a_press_facing_a_ball_notes_it(tmp_path):
    """record_interaction's A-press branch: a ball in front is an item-ball interaction."""
    ctx = make_ctx(tmp_path, memory={MAP: 13, PX: 9, PY: 5})
    ctx.facing = "RIGHT"
    ctx.mem.m(13).setdefault("npcs", {})["slot1:pic61"] = {
        "pic": 61, "slot": 1, "positions": {"10,5": 1}, "last": [10, 5], "text": "", "talked": 0, "moves": False}
    record_interaction(ctx, PressFrame("A", "agent", "test", before=(13, 9, 5), after=(13, 9, 5)))
    e = ctx.mem.m(13)["items"]["10,5"]
    assert e["seen"] == 1 and e["item"] is None  # no box opened: no item text yet


# --- Pickup behaviour ---------------------------------------------------------

def route_ctx(tmp_path, ball=(10, 5), player=(5, 5), m=13, xs=range(5, 12), ram=None):
    """A Route-2-like ctx: player on a visited corridor, one live ball sprite, goals far from parcel."""
    mem_cfg = {MAP: m, PX: player[0], PY: player[1], PARTY: 1}
    mem_cfg.update(ram or {})
    ctx = make_ctx(tmp_path, memory=mem_cfg)
    corridor(ctx.mem, m, player[1], xs)
    ball_sprite(ctx.emu, 1, ball[0], ball[1])
    return ctx


def test_pickup_applies_within_detour_and_walks_to_the_ball(tmp_path):
    ctx = route_ctx(tmp_path)
    assert applies(ctx)
    ctx.refresh()
    d = Pickup().step(ctx)
    assert d.rule == "pickup" and d.button == "RIGHT"  # 4 steps along the corridor to (9,5)
    ctx.emu.set(PX, 9)  # arrive at the spot beside the ball, still facing RIGHT
    ctx.facing = "RIGHT"
    ctx.refresh()
    d = Pickup().step(ctx)
    assert d.button == "A" and ctx.pickup_await == (13, 10, 5)


def test_pickup_detour_budget_boundary(tmp_path):
    # (5,5) -> the nearest side tile of a ball on row 5 is bx-6 steps; PICKUP_DETOUR is inclusive
    inside = route_ctx(tmp_path, ball=(5 + PICKUP_DETOUR + 1, 5), xs=range(5, 5 + PICKUP_DETOUR + 3))
    assert applies(inside)                                   # exactly PICKUP_DETOUR steps
    outside = route_ctx(tmp_path / "b", ball=(5 + PICKUP_DETOUR + 2, 5), xs=range(5, 5 + PICKUP_DETOUR + 4))
    assert not applies(outside)                              # one tile further is over budget


def test_pickup_does_not_apply_during_deliver_parcel(tmp_path):
    # carrying Oak's parcel with every earlier goal met -> goal_stage == "deliver_parcel"
    ctx = route_ctx(tmp_path, ram={
        0xD31D: 2, 0xD31E: 0x14, 0xD31F: 1, 0xD320: 0x46, 0xD321: 1,  # bag: POTION + OAK'S PARCEL
    })
    ctx.seen_maps = {0x0C, 0x01}   # to_route1, to_viridian; check_goals adds the current map itself
    ctx.battles_won = 1
    assert not ctx.goals()["deliver_parcel"] and goal_stage(ctx.goals()) == "deliver_parcel"
    assert not applies(ctx)


def test_pickup_does_not_apply_in_lab_before_first_pokemon(tmp_path):
    ctx = route_ctx(tmp_path, m=0x28, player=(6, 4), ball=(7, 4), xs=range(3, 10), ram={PARTY: 0})
    # still inside Oak's lab with no Pokemon: the starter planner owns those balls
    assert not applies(ctx)
    ctx.emu.set(PARTY, 1)  # a starter is in the party now: the lab gate lifts
    assert applies(ctx)


def test_pickup_skips_a_ball_after_two_empty_tries(tmp_path):
    ctx = route_ctx(tmp_path)
    ctx.pickup_tries[(13, 10, 5)] = 2
    assert not applies(ctx)
    ctx.pickup_tries[(13, 10, 5)] = 1  # one empty try still allows a second attempt
    assert applies(ctx)


def test_pickup_resolve_counts_a_failed_try_then_a_success(tmp_path):
    ctx = route_ctx(tmp_path, player=(9, 5))  # already beside the ball
    ctx.facing = "RIGHT"
    ctx.refresh()
    d = Pickup().step(ctx)
    assert d.button == "A" and ctx.pickup_await == (13, 10, 5)
    # the box closed with no item text -> one failed try, then it presses A again (tries=1 < 2)
    ctx.refresh()
    d = Pickup().step(ctx)
    assert ctx.pickup_tries[(13, 10, 5)] == 1 and d.button == "A"
    # now the dialog names an item -> success is recorded, no failed try added
    ctx.mem.note_item_ball(13, 10, 5, text="BCN found POTION!", seen=False)
    ctx.refresh()
    Pickup().step(ctx)
    assert ctx.mem.m(13)["items"]["10,5"]["item"] == "POTION"
    assert ctx.pickup_tries[(13, 10, 5)] == 1  # unchanged: the success did not add a failure


# --- legend: the '*' kind ------------------------------------------------------

def test_item_glyph_line_and_precedence():
    assert legend.glyph("item") == "*"
    assert "* an item ball" in legend.line({"item"})
    d = {"visited": {}, "npcs": {"slot1:pic61": {"pic": 61, "slot": 1, "positions": {"6,6": 1},
                                                  "last": [6, 6], "moves": False}}}
    item_map = tilekind.item_tiles(d)
    assert (6, 6) in item_map
    # item beats npc and object; a trainer still wins
    assert tilekind.classify(d, {}, {}, 1, 6, 6, None, {(6, 6)}, {}, items=item_map) == "item"
    assert tilekind.classify(d, {}, {}, 1, 6, 6, None, {(6, 6)}, {(6, 6): {"beaten": False}},
                             items=item_map) == "trainer"
    d2 = {"visited": {}, "interactions": {"6,5,DOWN": {"count": 1, "text": "BALL"}}}
    assert tilekind.classify(d2, {}, {}, 1, 6, 6, None, set(), {}, items={(6, 6)}) == "item"


def test_ascii_vision_and_render_memory_show_item_glyph(tmp_path):
    emu = FakeEmulator({TM + i: 0x10 for i in range(360)} | {MAP: 1, PX: 5, PY: 5})
    ball_sprite(emu, 1, 8, 8)  # map (8,8) -> screen (7,7)
    mem = MapMemory(tmp_path / "maps.json")
    mem.data["maps"]["1"] = {"visited": {}, "blocked": [], "warps": {}, "npcs": {
        "slot1:pic61": {"pic": 61, "slot": 1, "positions": {"8,8": 1}, "last": [8, 8],
                        "text": "", "talked": 0, "moves": False}}, "last_seen": 0}
    sees = ascii_vision(emu, mem, 1)
    assert sees[7][7] == "*" and "* an item ball" in sees.legend
    rows = mem.render_memory(1, 5, 5, {(7, 7)})
    assert rows[9][9] == "*" and "* an item ball" in rows.legend
