"""field_cut: CUT on the tree that closes the way to the Vermilion Gym door (stage vermilion_gym_entry).

Evidence (2026-11-16, 3000-step run from cut_taught.state): bicycle at step 424, back in Vermilion by 699, then 2,300 steps with no goal:
the Cut-free route planner had no way to the gym door (12,19) because the cuttable tree (15,18) closes the pocket in front of it, and no behaviour used CUT."""
from __future__ import annotations

from pathlib import Path

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import fan_club as fc, field_cut as fcut
from pokeagent.explorer.behaviours import FieldCut, default_behaviours
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.screentext import CHARMAP

ROM = Path(__file__).resolve().parents[1] / "roms" / "Pokemon Red.gb"
TM, MAP, MENU_ITEM = 0xC3A0, 0xD35E, 0xCC26
INVERSE = {v: k for k, v in CHARMAP.items() if len(v) == 1}
MON1 = 0xD16B


def _mem(moves=(15, 33, 0, 0), badges=0b10, party=2):
    mem = {0xD163: party, MAP: fc.VERMILION, 0xD362: 14, 0xD361: 18, 0xD356: badges, fcut.TILESET_ADDR: 0}
    for i in range(party):
        base = MON1 + 44 * i
        mem[0xD164 + i] = 1
        mem.update({base: 1, base + 33: 20, base + 1: 0, base + 2: 40, base + 34: 0, base + 35: 40})
        for k, mv in enumerate(moves if i == party - 1 else (33, 0, 0, 0)):  # the LAST member knows CUT
            mem[base + 8 + k] = mv
    return mem


def _draw(emu, rows, framed=False):
    for i in range(360):
        emu.set(TM + i, 0x7F)
    for r, text in enumerate(rows):
        row = 9 + r if framed else r
        if framed:
            emu.set(TM + 20 * row, 0x7C); emu.set(TM + 20 * row + 19, 0x7C)
        for c, ch in enumerate(text[:17]):
            emu.set(TM + 20 * row + (1 if framed else 0) + c, INVERSE.get(ch, 0x7F) if ch != ">" else 0xED)
    if framed:
        emu.set(TM + 20 * 8, 0x79); emu.set(TM + 20 * 8 + 1, 0x7A)


def _tree(emu, on=True, col_row=(10, 9)):
    emu.set(TM + 20 * col_row[1] + col_row[0], 0x3D if on else 0x39)


def _ctx(tmp_path, **kw):
    emu = FakeEmulator(_mem(**kw))
    for i in range(360):
        emu.set(TM + i, 0x39)
    _tree(emu)  # a tree on the tile to the RIGHT of the player
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=20)
    ctx.facing, ctx.step = "RIGHT", 100
    ctx.refresh()
    return ctx


def _go(ctx):
    ctx.refresh()
    ctx.opts.frames_per_step = 100  # one wait turn clears the pacing
    d = FieldCut().step(ctx)
    return FieldCut().step(ctx) if d is not None and d.rule == "field_cut_wait" else d


# --- the detection ----------------------------------------------------------------------------------------------------------

def test_tree_tile_ahead_is_read_off_the_tile_map_per_facing():
    tm = bytearray([0x39] * 360)
    tm[9 * 20 + 10] = 0x3D
    assert fcut.tree_ahead(bytes(tm), "RIGHT", 0) and not fcut.tree_ahead(bytes(tm), "LEFT", 0)
    assert not fcut.tree_ahead(bytes(tm), "RIGHT", 7)  # only the overworld tileset's tile 0x3D is a cuttable tree (the gym tileset uses 0x50)


def test_can_cut_needs_the_cascade_badge_and_a_member_with_cut():
    assert fcut.can_cut(FakeEmulator(_mem())) and fcut.cutter_slot(FakeEmulator(_mem())) == 1
    assert not fcut.can_cut(FakeEmulator(_mem(badges=0))) and not fcut.can_cut(FakeEmulator(_mem(moves=(33, 0, 0, 0))))


# --- the route ------------------------------------------------------------------------------------------------------------------

class _Plan:
    """A planner with a Cut-free pocket: no route without cut, a route through the tree (15, 18) with it."""
    def __init__(self):
        self.asked = []

    def __call__(self, start, goals, walls=None, blocked=None, hard=None, cut=False):
        self.asked.append(cut)
        return ["RIGHT", "DOWN", "DOWN"] if cut else None

    def follow(self, start, buttons):
        return [tuple(start), (start[0], start[1] + 1, start[2])]

    def trees(self, m):
        return {(15, 18)} if m == fc.VERMILION else set()


def test_route_goes_through_a_tree_only_when_the_party_can_cut():
    plan, pos = _Plan(), (fc.VERMILION, 14, 18)
    assert fc.route_step(fc.GYM_STAGE, pos, plan) is None                      # no cut state: the old behaviour (no way)
    assert fc.route_step(fc.GYM_STAGE, pos, plan, cut={"can": False}) is None
    st = {"can": True}
    out = fc.route_step(fc.GYM_STAGE, pos, plan, cut=st)
    assert out and out[0] == "RIGHT" and "Cut tree" in out[1]
    assert st["want"] == {"pos": pos, "dir": "RIGHT", "tree": (fc.VERMILION, 15, 18)}


def test_plan_goal_hands_the_planner_the_cut_state(tmp_path):
    ctx = _ctx(tmp_path)
    st = fcut.offer(ctx)
    assert st["can"] and st is fcut.state(ctx)
    assert not fcut.offer(_ctx(tmp_path, badges=0))["can"]


@pytest.mark.skipif(not ROM.exists(), reason="needs the ROM")
def test_rom_vermilion_gym_door_is_only_reachable_through_the_cut_tree():
    from pokeagent.atlas.walkgrid import rom_cave_planner
    plan = rom_cave_planner(str(ROM), maps=fc.PLANNER_MAPS)
    assert plan.trees(fc.VERMILION) == {(15, 18)}
    start = (fc.VERMILION, 18, 1)
    assert plan(start, {fc.GYM_DOOR}) is None
    path = plan(start, {fc.GYM_DOOR}, cut=True)
    assert path and (fc.VERMILION, 15, 18) in plan.follow(start, path) and plan.follow(start, path)[-1] == fc.GYM_DOOR
    st = {"can": True}
    out = fc.route_step(fc.GYM_STAGE, (fc.VERMILION, 14, 18), plan, cut=st)
    assert out and out[0] == "RIGHT" and st["want"]["tree"] == (fc.VERMILION, 15, 18)


# --- the menu path ------------------------------------------------------------------------------------------------------------------

def test_behaviour_is_registered_before_the_dialog_and_menu_drivers():
    names = [b.name for b in default_behaviours()]
    assert names.index("field_cut") < names.index("advance_dialog") < names.index("menu") < names.index("plan_goal")


def test_behaviour_waits_for_a_request_then_opens_start(tmp_path):
    ctx = _ctx(tmp_path)
    assert not FieldCut().applies(ctx)                                   # nothing asked for
    fcut.request(fcut.state(ctx), ctx.pos(), "RIGHT", (fc.VERMILION, 15, 18))
    assert FieldCut().applies(ctx)
    assert _go(ctx).button == "START"
    ctx.facing = "UP"
    assert not FieldCut().applies(ctx) or fcut.state(ctx)["seq"] is not None  # a sequence in progress owns the screen
    ctx2 = _ctx(tmp_path)
    fcut.request(fcut.state(ctx2), ctx2.pos(), "RIGHT", (fc.VERMILION, 15, 18))
    ctx2.facing = "UP"
    assert not FieldCut().applies(ctx2)                                  # not facing the tree: the planner's turn press comes first


def test_start_menu_party_list_member_menu_then_cut(tmp_path):
    ctx = _ctx(tmp_path)
    fcut.request(fcut.state(ctx), ctx.pos(), "RIGHT", (fc.VERMILION, 15, 18))
    assert _go(ctx).button == "START"
    _draw(ctx.emu, ["POKEDEX", ">POKeMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT"], framed=True)
    ctx.emu.set(MENU_ITEM, 0)
    d = _go(ctx)
    assert d.button == "DOWN" or d.button == "A"                         # the cursor row is compared with the POKeMON row
    ctx.emu.set(MENU_ITEM, 1)
    assert _go(ctx).button == "A"
    _draw(ctx.emu, ["Choose a POKeMON.", ">BULBA", "BULBA"])
    ctx.emu.set(MENU_ITEM, 0)
    assert _go(ctx).button == "DOWN"                                     # slot 1 knows CUT
    ctx.emu.set(MENU_ITEM, 1)
    assert _go(ctx).button == "A"
    _draw(ctx.emu, [">CUT", "STATS", "Choose a P SWITCH", "CANCEL"], framed=True)  # the party text fuses with the box row on the left
    ctx.emu.set(MENU_ITEM, 1)                                            # on STATS: CUT is row 0
    assert _go(ctx).button == "UP"
    ctx.emu.set(MENU_ITEM, 0)
    assert _go(ctx).button == "A" and fcut.state(ctx)["seq"]["chosen"]
    _draw(ctx.emu, ["BULBA hacked away", "with CUT!"], framed=True)      # the text, tree still there
    assert _go(ctx).button == "A"
    for i in range(360):
        ctx.emu.set(TM + i, 0x39)                                        # overworld again, the tree is gone
    d = _go(ctx)
    assert d.rule == "field_cut_done" and fcut.state(ctx)["seq"] is None and fcut.state(ctx)["cuts"] == 1


def test_a_failed_try_is_capped_and_cools_down(tmp_path):
    ctx = _ctx(tmp_path)
    st = fcut.state(ctx)
    fcut.request(st, ctx.pos(), "RIGHT", (fc.VERMILION, 15, 18))
    for _ in range(fcut.PRESS_CAP + 1):
        _go(ctx)
        if st["seq"] is None:
            break
    assert st["seq"] is None and st["cooldown_until"] > ctx.step and st["tries"][(fc.VERMILION, 15, 18)] == 1
    assert not fcut.offer(ctx)["can"] and not FieldCut().applies(ctx)   # cooling down: the planner stops asking
    st["tries"][(fc.VERMILION, 15, 18)] = fcut.MAX_TRIES
    ctx.step = st["cooldown_until"] + 1
    fcut.request(st, ctx.pos(), "RIGHT", (fc.VERMILION, 15, 18))
    assert not FieldCut().applies(ctx)                                   # out of tries for that tree


def test_nothing_to_cut_text_ends_the_try(tmp_path):
    ctx = _ctx(tmp_path)
    st = fcut.state(ctx)
    fcut.request(st, ctx.pos(), "RIGHT", (fc.VERMILION, 15, 18))
    _go(ctx)
    _draw(ctx.emu, ["There isn't", "anything to CUT!"], framed=True)
    d = _go(ctx)
    assert d.rule == "field_cut_failed" and st["seq"] is None and st["tries"]


def test_a_tree_cut_failed_three_times_is_no_longer_routed_through(tmp_path):
    ctx = _ctx(tmp_path)
    st, tree, pos = fcut.state(ctx), (fc.VERMILION, 15, 18), (fc.VERMILION, 14, 18)
    assert fc.route_step(fc.GYM_STAGE, pos, _Plan(), cut=fcut.offer(ctx))[0] == "RIGHT"
    st["tries"][tree] = fcut.MAX_TRIES
    st["want"] = {"pos": pos, "dir": "RIGHT", "tree": tree}
    offer = fcut.offer(ctx)
    assert tree in offer["blocked"]
    assert fc.route_step(fc.GYM_STAGE, pos, _Plan(), cut=offer) is None and st["want"] is None


# --- marathon-2026-11-16c: the Vermilion tree was never cut ---------------------------------------------------------------------------

def test_field_cut_menu_presses_are_never_loop_vetoed():
    """Live run: the party-list cursor moves do not change the screen text, so the loop ledger vetoed DOWN/A after 3 and swapped in B: CUT never ran."""
    from pokeagent.explorer.loop_memory import NEVER_VETO
    assert "field_cut" in NEVER_VETO


def test_a_cooling_down_try_holds_at_the_tree_instead_of_giving_the_stage_to_exploration():
    """After a failed try (400-step cooldown) the planner returned None and exploration walked off through Route 11 and Diglett's Cave."""
    plan, pos = _Plan(), (fc.VERMILION, 14, 18)
    assert fc.route_step(fc.GYM_STAGE, pos, plan, cut={"can": False, "hold": False}) is None  # no cutter / badge: not held
    st = {"can": False, "hold": True}
    out = fc.route_step(fc.GYM_STAGE, pos, plan, cut=st)
    assert out and out[0] == "RIGHT" and "cooling down" in out[1] and not st.get("want")


def test_offer_marks_hold_only_during_the_cooldown(tmp_path):
    ctx = _ctx(tmp_path)
    st = fcut.state(ctx)
    st["cooldown_until"] = ctx.step + 50
    assert fcut.offer(ctx)["hold"] and not fcut.offer(ctx)["can"]
    ctx.step += 51
    assert not fcut.offer(ctx)["hold"] and fcut.offer(ctx)["can"]
