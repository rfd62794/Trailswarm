"""Stretch warp + layout overrides (synthetic, no ROM)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from pokeagent.atlas import anchor, fit, inplace
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.stretch import stretch_image, stretch_layout, stretch_warp
from pokeagent.atlas.warp import AxisWarp, Warp, merge_inserts, resample
from pokeagent.atlas.world import CELL, Place, WorldLayout, Xform
from pokeagent.world.view import locate
from test_inplace import hdr, walkgrid, world


def test_axis_warp_monotonic_and_invertible():
    w = AxisWarp(((3, 2), (7, 4)))
    xs = np.linspace(-1, 12, 131)
    ys = [w.fwd(x) for x in xs]
    assert all(b > a for a, b in zip(ys, ys[1:]))
    assert all(w.inv(w.fwd(x)) == pytest.approx(x) for x in xs)
    assert w.fwd(3) == 3 and w.fwd(4) == 4 + 2 and w.fwd(8) == 8 + 2 + 4 and w.total == 6


def test_warp_keeps_connected_maps_contiguous():
    wp = Warp(AxisWarp(((5, 3),)), AxisWarp(((2, 1),)))
    a_end, b_start = 10, 10                    # map A spans 0..10, B starts where A ends (a connection edge)
    assert wp.x.fwd(a_end) == wp.x.fwd(b_start)
    for edge in (0, 5, 6, 10, 20):             # a map's far edge never overlaps the next map
        assert wp.x.fwd(edge + 1) > wp.x.fwd(edge)


def test_resample_repeats_the_inserted_cell():
    img = np.zeros((2 * CELL, 3 * CELL, 3), np.uint8)
    for c in range(3):
        img[:, c * CELL:(c + 1) * CELL] = 10 * (c + 1)
    out = resample(img, Warp(AxisWarp(((1, 2),)), AxisWarp()), 2)
    assert out.shape == (2 * CELL, 5 * CELL, 3)
    assert [int(out[0, c * CELL, 0]) for c in range(5)] == [10, 20, 20, 20, 30]


def test_merge_inserts_sums_and_sorts():
    assert merge_inserts({5: 1, 2: 2}, {5: 3, 9: 0}) == ((2, 2), (5, 4))


def stretched():
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    wk = walkgrid(10, 10)
    wk[4:5, 2:7] = False                       # building footprint 5 wide x 2 tall at door (5,5)
    wp = stretch_warp(a, L, lambda m: wk)
    return H, L, a, wk, wp


def test_stretch_warp_gives_footprint_full_size():
    H, L, a, wk, wp = stretched()
    assert wp.x.total >= 0 and wp.y.total > 0
    L2 = stretch_layout(L, wp)
    xf = fit.build_xforms(a, L2, lambda m: wk, True)
    assert xf[10].s == 1.0 and xf[11].s == 1.0          # fits at full size once stretched
    assert L2.to_world(0, 5, 5) == (round(wp.x.fwd(9) * CELL), round(wp.y.fwd(9) * CELL))
    assert L2.outdoor_height == L.outdoor_height + wp.y.total and L2.places[10].y == L.places[10].y + wp.y.total


def test_stretch_image_appends_inset_unchanged():
    H, L, a, wk, wp = stretched()
    base = np.zeros((L.height * CELL, L.width * CELL, 3), np.uint8)
    base[L.outdoor_height * CELL:] = 99
    out = stretch_image(base, L, wp)
    L2 = stretch_layout(L, wp)
    assert out.shape[0] == L2.height * CELL and out.shape[1] >= L2.width * CELL - 1
    assert (out[L2.outdoor_height * CELL:, :L.width * CELL] == 99).all()


def test_click_to_tile_round_trips_through_the_warp():
    H, L, a, wk, wp = stretched()
    L2 = stretch_layout(L, wp)
    for x, y in ((0, 0), (3, 4), (9, 9)):
        px, py = L2.to_world(0, x, y)
        assert locate(L2, px + 2, py + 2) == (0, x, y)
    px, py = L2.to_world(12, 1, 1)                 # inset grid below keeps plain cell lookup
    assert locate(L2, px + 2, py + 2)[0] == 12


def test_agent_coords_follow_stretch_in_place():
    H, L, a, wk, wp = stretched()
    L2 = stretch_layout(L, wp)
    xf = fit.build_xforms(a, L2, lambda m: wk, True)
    vl = inplace.view_layout(L2, a, xf, {10})
    t = xf[10]
    assert vl.to_world(10, 1, 3) == (round((t.ox + 1) * CELL), round((t.oy + 3) * CELL))
    assert vl.to_world(11, 0, 0) == (round((t.ox + 3) * CELL), round(t.oy * CELL))   # unshown floor pinned to its stair in the shown 1F
    vl2 = inplace.view_layout(L2, a, xf, set())
    assert vl2.to_world(11, 0, 0) == vl2.to_world(0, 5, 5)                          # nothing shown: the warped door


def test_overrides_merge_apply_and_save(tmp_path):
    d, u = tmp_path / "d.json", tmp_path / "u.json"
    d.write_text(json.dumps({"interiors": {"10": {"dx": 1, "hidden": False}}, "bands": {"x": {"4": 2}}}))
    u.write_text(json.dumps({"interiors": {"10": {"dy": 2.5}, "12": {"hidden": True}}, "bands": {"x": {"4": 1}, "y": {"7": 3}}}))
    ov = Overrides.load(u, d)
    assert ov.interiors[10] == {"dx": 1, "hidden": False, "dy": 2.5} and ov.hidden == {12}
    assert ov.bands == {"x": {4: 3}, "y": {7: 3}}
    t = ov.adjust(10, Xform(10.0, 10.0, 0.5), (2, 4))
    assert t == Xform(11.0, 12.5, 0.5)
    ov.set(11, scale=1.0)
    t = ov.adjust(11, Xform(10.0, 10.0, 0.5), (2, 4))              # scale about the entry tile keeps the door fixed
    assert (t.ox + 2 * t.s, t.oy + 4 * t.s) == (10 + 2 * 0.5, 10 + 4 * 0.5) and t.s == 1.0
    ov.move(12, 1, 1); ov.rescale(12, 0.5, 2); ov.rescale(12, 0.5, 100)
    assert ov.interiors[12]["scale"] == 2.0
    ov.save(tmp_path / "out" / "o.json")
    assert Overrides.load(tmp_path / "out" / "o.json", None).interiors[12]["dx"] == 1
    ov.reset(12); assert 12 not in ov.interiors
    assert Overrides.load(tmp_path / "missing.json", None).interiors == {}


def test_plan_applies_overrides_to_floors_hidden_and_inset():
    H, L = world()
    ov = Overrides()
    ov.set(10, dx=2)
    base = inplace.plan_interiors(b"", H, L, None, {0: None})
    moved = inplace.plan_interiors(b"", H, L, None, {0: None}, ov)
    assert moved.fit[10].ox == base.fit[10].ox + 2 and moved.fit[11].ox == base.fit[11].ox + 2      # floors follow their building
    ov2 = Overrides(); ov2.set(10, mode="inset"); ov2.set(12, hidden=True)
    p = inplace.plan_interiors(b"", H, L, None, {0: None}, ov2)
    assert 10 not in p.anchors and 11 not in p.anchors and 12 in p.anchors       # an inset interior takes its floors with it
    assert 12 not in inplace.shown_set("inplace", p.anchors, 1.0, hidden=p.hidden)
    ov3 = Overrides(); ov3.set(10, mode="inplace_full")
    p3 = inplace.plan_interiors(b"", H, L, None, {0: None}, ov3)
    assert p3.fit[10] == p3.full[10]
