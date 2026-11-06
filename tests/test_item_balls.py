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


def ball_sprite(emu, slot: int, x: int, y: int, pic: int = 61, moving: bool = False, img: int = 0x9C) -> None:
    """A sprite-table slot as the ROM has it: pic at 0xC1x0, movement status 1 at +1, image index at +2
    (0xFF = hidden/not drawn), map pos (x+4, y+4) at 0xC2x4/5, movement byte at 0xC2x6 (0xFF stay, 0xFE walk)."""
    emu.set(0xC100 + 16 * slot, pic)
    emu.set(0xC101 + 16 * slot, 1)
    emu.set(0xC102 + 16 * slot, img)
    emu.set(0xC206 + 16 * slot, 0xFE if moving else 0xFF)
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
    ball_sprite(emu, 2, 30, 30, moving=True)       # pic 61 but a random-walk sprite (movement byte 0xFE)
    emu.set(0xC130, 61); emu.set(0xC131, 0)        # pic 61 but no map position (raw 0 -> -4,-4)
    ball_sprite(emu, 4, 15, 15, pic=7)             # an ordinary NPC
    ball_sprite(emu, 5, 40, 40)                    # a second real item ball
    ball_sprite(emu, 15, 50, 50)                   # the last slot counts too
    assert items.item_balls(emu) == [(1, 10, 20), (5, 40, 40), (15, 50, 50)]


def test_item_balls_skips_a_hidden_sprite_in_view_but_keeps_an_offscreen_ff():
    """Gen 1 HideObject leaves pic 61 and the position and sets the image index 0xFF; an off-screen live
    ball also reads 0xFF (not drawn), so only an 0xFF ball inside the view window counts as hidden."""
    emu = FakeEmulator({PX: 10, PY: 10})
    ball_sprite(emu, 1, 11, 10, img=0xFF)      # next to the player, hidden: collected
    ball_sprite(emu, 2, 10, 14, img=0xFF)      # 4 tiles away, hidden
    ball_sprite(emu, 3, 30, 10, img=0xFF)      # far away, 0xFF only because it is off screen: still live
    ball_sprite(emu, 4, 12, 10, img=0xA4)      # in view and drawn: live
    assert items.item_balls(emu) == [(3, 30, 10), (4, 12, 10)]
    assert items.hidden_balls(emu, within=2) == [(1, 11, 10)]


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


def test_pickup_never_applies_in_oaks_lab_even_with_a_pokemon(tmp_path):
    ctx = route_ctx(tmp_path, m=0x28, player=(6, 4), ball=(7, 4), xs=range(3, 10), ram={PARTY: 0})
    assert not applies(ctx)       # before the first pokemon the starter planner owns those balls
    ctx.emu.set(PARTY, 1)         # a starter is in the party: the two leftover balls are still not ours
    assert not applies(ctx)


def test_pickup_skips_a_ball_after_two_empty_tries(tmp_path):
    ctx = route_ctx(tmp_path)
    ctx.pickup_tries[(13, 10, 5)] = 2
    assert not applies(ctx)
    ctx.pickup_tries[(13, 10, 5)] = 1  # one empty try still allows a second attempt
    assert applies(ctx)


def beside(tmp_path, **kw):
    """Player already beside the ball (facing it): the next Pickup step presses A."""
    ctx = route_ctx(tmp_path, player=(9, 5), **kw)
    ctx.facing = "RIGHT"
    return ctx


def press_a(ctx):
    ctx.refresh()
    d = Pickup().step(ctx)
    return d.button if d else None


def test_success_is_decided_by_this_presses_dialog_not_persisted_memory(tmp_path):
    ctx = beside(tmp_path)
    # maps.json remembers an item from an earlier run / an earlier walk-over: that is NOT this press's result
    ctx.mem.note_item_ball(13, 10, 5, text="BCN found POTION!", seen=False)
    assert press_a(ctx) == "A" and ctx.pickup_await == (13, 10, 5)
    assert press_a(ctx) == "A"                      # the press had no dialog: a failed try, press again
    assert ctx.pickup_tries[(13, 10, 5)] == 1
    assert press_a(ctx) is None                     # second empty try: the ball is skipped for the run
    assert ctx.pickup_tries[(13, 10, 5)] == 2


def test_a_dialog_with_an_item_is_a_success_and_a_hidden_ball_is_never_pressed_again(tmp_path):
    ctx = beside(tmp_path)
    assert press_a(ctx) == "A"
    ctx.ball_result = (13, 10, 5, "POTION")         # press_interact: this press closed on "found POTION!"
    ball_sprite(ctx.emu, 1, 10, 5, img=0xFF)        # and the game hid the sprite
    assert press_a(ctx) is None                     # resolved as a success; nothing left to pick
    assert ctx.pickup_tries.get((13, 10, 5), 0) == 0 and (13, 10, 5) in ctx.pickup_gone


def test_a_ball_that_stays_visible_after_success_does_not_loop(tmp_path):
    ctx = beside(tmp_path)
    presses = 0
    for _ in range(10):
        b = press_a(ctx)
        if b != "A":
            break
        presses += 1
        ctx.ball_result = (13, 10, 5, "POTION")     # every press "succeeds", yet the sprite never hides
    assert presses == 2                             # a success with the ball still live counts as a try
    assert ctx.pickup_tries[(13, 10, 5)] == 2
    assert not applies(ctx)


def test_a_ball_hidden_before_we_arrive_is_not_chosen_and_remembered_as_gone(tmp_path):
    ctx = beside(tmp_path)
    ball_sprite(ctx.emu, 1, 10, 5, img=0xFF)        # walked over earlier: pic 61 stays, image index 0xFF
    assert not applies(ctx)
    assert press_a(ctx) is None
    assert (13, 10, 5) in ctx.pickup_gone
    ball_sprite(ctx.emu, 1, 10, 5, img=0xFF)
    ctx.emu.set(PX, 4)                              # walked away: 0xFF now reads as off screen, still not chosen
    assert not applies(ctx)


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


# --- the A press returns before the box opens ----------------------------------

def test_await_item_dialog_waits_for_the_late_box_and_records_this_presses_item(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import pickup
    ctx = make_ctx(tmp_path)
    shown = iter([None, None, None, "BCN found", "BCN found | POTION!"])
    monkeypatch.setattr(pickup, "read_box", lambda c: next(shown, None))
    pickup.await_item_dialog(ctx, (13, 10, 5))
    assert ctx.ball_result == (13, 10, 5, "POTION") and ctx.emu.frames >= 24
    monkeypatch.setattr(pickup, "read_box", lambda c: None)  # nothing ever opens: no result, bounded wait
    pickup.await_item_dialog(ctx, (13, 10, 5))
    assert ctx.ball_result is None


def test_the_a_decision_carries_the_dialog_hook(tmp_path):
    ctx = beside(tmp_path)
    ctx.refresh()
    d = Pickup().step(ctx)
    assert d.button == "A" and d.after is not None


# --- a ball in unexplored ground: approach it ---------------------------------

def test_pickup_explores_toward_a_ball_whose_side_tiles_are_unvisited(tmp_path):
    from pokeagent.explorer.behaviours.pickup_approach import APPROACH_STEPS
    ctx = route_ctx(tmp_path, ball=(8, 3), player=(5, 5), xs=range(5, 12))  # corridor on row 5, ball two rows up
    assert applies(ctx)
    ctx.refresh()
    d = Pickup().step(ctx)
    assert d.rule == "pickup" and d.button == "UP" and ctx.pickup_approach[(13, 8, 3)] == 1
    ctx.pickup_approach[(13, 8, 3)] = APPROACH_STEPS   # spent its approach budget: given up for the run
    assert not applies(ctx)


def test_pickup_does_not_explore_toward_a_ball_beyond_the_detour_budget(tmp_path):
    ctx = route_ctx(tmp_path, ball=(5 + PICKUP_DETOUR + 5, 3), player=(5, 5), xs=range(5, 12))
    assert not applies(ctx)
