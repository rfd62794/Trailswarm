"""In-place interiors: anchoring, footprint/fit, z-order, modes, agent mapping (synthetic - no ROM)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pokeagent.atlas import anchor, fit, inplace
from pokeagent.atlas.rom_maps import MapHeader
from pokeagent.atlas.world import CELL, Place, WorldLayout
from pokeagent.world import anim
from pokeagent.world.model import Track
from pokeagent.world.view import locate
from conftest import hdr, walkgrid, world


def test_anchor_door_alignment_and_chain():
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    h = a[10]
    assert (h.x + h.entry[0], h.y + h.entry[1]) == (4 + 5, 4 + 5) and h.depth == 1 and h.parent == 0 and h.source == "rom"
    f2 = a[11]                                  # 2F arrival tile sits on 1F's stair tile
    assert (f2.x + f2.entry[0], f2.y + f2.entry[1]) == (h.x + 3, h.y + 0) and f2.depth == 2 and f2.parent == 10
    assert a[12].depth == 1 and a[12].source == "rom"


def test_anchor_learned_fallback_and_unanchorable():
    H, L = world()
    model = {"maps": {"0": {"warps": {"6,6,UP": [13, 1, 1]}}}}
    a = anchor.anchor_interiors(H, L, model)
    assert a[13].source == "learned" and (a[13].x + 1, a[13].y + 1) == (4 + 6, 4 + 6)
    assert 14 not in a                          # nothing leads there: stays inset
    assert 13 not in anchor.anchor_interiors(H, L)


def test_bad_dest_warp_falls_back_to_exit_warp():
    H, L = world()
    H[0].warps[0] = (5, 5, 9, 10)               # index out of range -> first warp back to the parent
    assert anchor.anchor_interiors(H, L)[10].entry == (1, 3)


def test_footprint_detects_building_block():
    wk = walkgrid()
    wk[4:8, 6:11] = False                       # building 5 wide x 4 tall; door below at (8, 8)
    assert fit.footprint(wk, (8, 8)) == (6, 4, 11, 9)


def test_footprint_merged_with_scenery_falls_back():
    wk = walkgrid(40, 20)
    wk[4:8, :] = False                          # a tree line running off the limit
    x0, y0, x1, y1 = fit.footprint(wk, (20, 8))
    assert (x1 - x0, y1 - y0) == fit.FALLBACK and y1 == 9
    assert fit.footprint(None, (5, 5))[3] == 6


def test_choose_scale_and_minimum():
    assert fit.choose_scale(8, 8, 8, 8) == 1.0
    assert fit.choose_scale(8, 8, 6, 6) == 0.75
    assert fit.choose_scale(8, 8, 5, 4) == 0.5
    assert fit.choose_scale(20, 20, 5, 4) == fit.MIN_SCALE      # still overflows


def test_build_xforms_scale_and_floors_share_scale():
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    wk = walkgrid(10, 10)
    wk[4:5, 2:7] = False                        # footprint 5 wide x 2 tall, door at (5,5)
    xf = fit.build_xforms(a, L, lambda m: wk, True)
    assert xf[10].s == 0.5 and xf[11].s == 0.5
    assert xf[10].ox >= 4 + 2 and xf[10].ox + 4 * 0.5 <= 4 + 7             # inside the building
    t, u = xf[10], xf[11]                       # stairs line up in the fitted transform
    assert (u.ox + 3 * u.s, u.oy + 0 * u.s) == pytest.approx((t.ox + 3 * t.s, t.oy))
    full = fit.build_xforms(a, L, lambda m: wk, False)
    assert full[10] == (a[10].x, a[10].y, 1.0)


def test_shown_set_modes():
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    assert inplace.shown_set("inset", a, 5.0) == set()
    assert inplace.shown_set("inplace", a, 0.05) == set(a)
    assert inplace.shown_set("auto", a, 0.1) == set()
    assert inplace.shown_set("auto", a, 1.0) == set(a)                      # zoomed in
    assert inplace.shown_set("auto", a, 0.1, hover=11) == {10, 11}          # a floor brings its parents
    assert inplace.shown_set("auto", a, 0.1, inside=(12,)) == {12}


def test_z_order_deeper_above_and_top_last():
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    assert inplace.z_order(a, {10, 11, 12}) == [10, 12, 11]
    assert inplace.z_order(a, {10, 11, 12}, top=10) == [12, 11, 10]


def view(mode, shown):
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    wk = walkgrid(10, 10)
    wk[4:5, 2:7] = False
    p = inplace.Plan(a, fit.build_xforms(a, L, lambda m: wk, True), fit.build_xforms(a, L, lambda m: wk, False))
    return L, p, inplace.view_layout(L, a, p.xf(mode), shown)


def test_agent_mapping_in_place_full_and_fit():
    L, p, vl = view("inplace_full", {10})
    a = p.anchors[10]
    assert vl.to_world(10, 1, 3) == ((a.x + 1) * CELL, (a.y + 3) * CELL) == vl.to_world(0, 5, 5)
    L, p, vl = view("inplace", {10})
    t = vl.xf[10]
    assert t.s < 1.0
    assert vl.to_world(10, 2, 2) == (round((t.ox + 2 * t.s) * CELL), round((t.oy + 2 * t.s) * CELL))


def test_agent_mapping_not_shown_pins_to_door_with_badge():
    L, p, vl = view("inplace", set())
    assert vl.to_world(10, 3, 0) == vl.to_world(0, 5, 5) == vl.to_world(11, 0, 0)
    assert inplace.badge(vl, 11).startswith("inside: ") and inplace.badge(vl, 0) is None
    t = Track("a", map=10, x=1, y=1, )
    t.path.extend([(10, 0, 0), (10, 1, 1)])
    assert anim.place(t, vl, 0.0)[:2] == tuple(float(v) for v in vl.to_world(0, 5, 5))
    assert anim.trail_points(t, vl) == [(vl.to_world(0, 5, 5)[0] + 8, vl.to_world(0, 5, 5)[1] + 8)] * 2


def test_agent_mapping_inset_is_unchanged_and_unanchored_stays_inset():
    L, p, vl = view("inset", set())
    H, L2 = world()
    assert L2.to_world(14, 1, 1) == vl.to_world(14, 1, 1)                   # unanchorable: its inset place
    assert 14 not in vl.pins


def test_locate_prefers_topmost_in_place_floor():
    L, p, vl = view("inplace_full", {10, 11})
    t2 = vl.xf[11]
    cx, cy = t2.ox + 1.5, t2.oy + 1.5
    got = locate(vl, cx * CELL, cy * CELL)
    assert got[0] == 11 and got[1:] == (1, 1)
    assert inplace.hit(vl, p.anchors, p.full, cx, cy)== 11


def test_legend_lines():
    L, p, vl = view("inplace", {10})
    lines = inplace.legend(p.anchors, p.fit, 11)
    assert any("scaled to 50%" in s for s in inplace.legend(p.anchors, p.fit, 10))
    assert "floor level 2" in lines[0]
    assert inplace.legend(p.anchors, p.fit, 99)[0].endswith("(inset)")
