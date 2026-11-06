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
from conftest import walkgrid, world


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


def test_stretch_inserts_beside_the_building_not_inside_it():
    H, L, a, wk, wp = stretched()
    gx, gy = fit.gap_cells(wk, fit.footprint(wk, (5, 5)), (5, 5))
    fx0, fy0, fx1, fy1 = fit.footprint(wk, (5, 5))
    assert gx < fx0 and gy < fy0                                    # the ground outside, never a building cell
    assert all(not (4 + fx0 <= p < 4 + fx1) for p, _ in wp.x.inserts)
    assert all(not (4 + fy0 <= p < 4 + fy1) for p, _ in wp.y.inserts)
    assert (4 + gy) in [p for p, _ in wp.y.inserts]                 # the 4-cell-tall room needed one more row: added in the ground above


def test_remap_view_keeps_the_same_place():
    from pokeagent.atlas.stretch import remap_view
    H, L, a, wk, wp = stretched()
    L2 = stretch_layout(L, wp)
    px, py = L.to_world(0, 7, 8)
    nx, ny = remap_view(L, L2, px, py)
    assert (nx, ny) == pytest.approx(L2.to_world(0, 7, 8))
    assert remap_view(L2, L, nx, ny) == pytest.approx((px, py))                       # and back
    ix, iy = L.to_world(12, 1, 1)
    assert remap_view(L, L2, ix, iy) == pytest.approx(L2.to_world(12, 1, 1))          # the inset grid just shifts down


def test_overrides_save_only_the_user_layer_and_atomically(tmp_path):
    d, u = tmp_path / "d.json", tmp_path / "u.json"
    d.write_text(json.dumps({"interiors": {"10": {"dx": 1}}, "bands": {"x": {"4": 2}}}))
    ov = Overrides.load(u, d)
    ov.move(11, 1, 0)
    ov.save()
    ov.save()
    saved = json.loads(u.read_text())
    assert saved["interiors"] == {"11": {"dx": 1.0, "dy": 0.0}} and saved["bands"] == {"x": {}, "y": {}}   # no defaults copied in
    assert not list(tmp_path.glob("*.tmp"))
    assert Overrides.load(u, d).bands["x"] == {4: 2}                                                        # no doubling
    ov.reset(10)
    assert ov.interiors[10] == {"dx": 1}                                                                    # defaults survive a reset


def test_overrides_bad_values_dropped_on_load(tmp_path, caplog):
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"interiors": {"10": {"dx": "x", "scale": 99, "mode": "bogus", "hidden": 1}, "zz": {"dx": 1},
                                           "11": "nope"}, "bands": {"x": {"3": "a", "4": 99}}}))
    ov = Overrides.load(u, None)
    assert ov.interiors == {10: {"scale": 2.0, "hidden": True}}
    assert ov.bands["x"] == {4: 16}
    assert "dropped" in caplog.text


def test_plan_shift_moves_building_and_its_floors_live():
    H, L = world()
    p = inplace.plan_interiors(b"", H, L, None, {0: None})
    before = dict(p.fit), dict(p.full)
    p.shift(10, 1.5, -2)
    assert p.fit[10].ox == before[0][10].ox + 1.5 and p.full[11].oy == before[1][11].oy - 2
    assert p.fit[12] == before[0][12]                                                  # another building untouched


def test_edit_save_is_debounced_not_per_change(tmp_path):
    from types import SimpleNamespace
    from pokeagent.viewer.ui.world_edit import EditLayout
    saves = []
    layer = SimpleNamespace(ov=SimpleNamespace(save=lambda: saves.append(1)))
    e = EditLayout(layer)
    for _ in range(20):
        e.touch(True)
    e.tick(e._dirty_at + 0.1)
    assert saves == []                                  # a burst of wheel notches writes nothing yet
    e.tick(e._dirty_at + 0.6)
    assert saves == [1]
    e.tick(e._dirty_at or 0); e.flush()
    assert saves == [1]                                 # clean: no more writes


def test_layer_failure_falls_back_to_plain_layout_once(monkeypatch):
    from types import SimpleNamespace
    from pokeagent.viewer.ui import world_interiors as wi
    H, L = world()
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise ValueError("bad override")
    monkeypatch.setattr(wi.inplace, "plan_interiors", boom)
    view = SimpleNamespace(world=SimpleNamespace(layout=L, rom=b"", headers=H), wm=SimpleNamespace(rev=0, union_model=lambda: {}))
    layer = wi.InteriorLayer(view)
    assert layer.layout(1.0, ()) is L and layer.shown == set() and layer.vl is None
    assert layer.layout(1.0, ()) is L and len(calls) == 1          # same inputs: not retried every frame
    layer.mode = "inplace"
    layer.layout(1.0, ())
    assert len(calls) == 2                                          # inputs changed: tried again


def test_gap_cells_never_negative_at_the_map_edge():
    wk = walkgrid(10, 10)
    wk[0:2, 0:3] = False
    fp = fit.footprint(wk, (1, 2))
    gx, gy = fit.gap_cells(wk, (0, 0, 3, 3), (1, 2))
    assert gx >= 0 and gy >= 0 and fp[0] >= 0


def test_overrides_load_survives_wrong_json_types(tmp_path):
    for body in ({"interiors": [1, 2]}, {"bands": {"x": [5], "y": 7}}, {"bands": [1]}, {"interiors": {"10": [1], "11": None}}, [1, 2]):
        u = tmp_path / "u.json"
        u.write_text(json.dumps(body))
        ov = Overrides.load(u, None)
        assert ov.interiors == {} and ov.bands == {"x": {}, "y": {}}
    u.write_text("{not json")
    assert Overrides.load(u, None).interiors == {}


def test_overrides_edits_are_deltas_over_defaults(tmp_path):
    d, u = tmp_path / "d.json", tmp_path / "u.json"
    d.write_text(json.dumps({"interiors": {"10": {"dx": 3, "dy": -1}}}))
    ov = Overrides.load(u, d)
    ov.move(10, 0.5, 0)
    assert ov.user["interiors"][10] == {"dx": 0.5, "dy": 0.0}               # only the delta is stored
    assert ov.interiors[10] == {"dx": 3.5, "dy": -1.0}                      # applied on top of the default
    ov.save()
    assert json.loads(u.read_text())["interiors"]["10"] == {"dx": 0.5, "dy": 0.0}
    t = Overrides.load(u, d).adjust(10, Xform(10.0, 10.0, 1.0), (0, 0))
    assert (t.ox, t.oy) == (13.5, 9.0)


def test_edit_flush_stays_dirty_when_save_fails():
    from types import SimpleNamespace
    from pokeagent.viewer.ui.world_edit import EditLayout
    tries = []

    def save():
        tries.append(1)
        if len(tries) == 1:
            raise OSError("disk full")
    e = EditLayout(SimpleNamespace(ov=SimpleNamespace(save=save)))
    e.touch()
    e.flush()
    assert e._dirty_at is not None                                         # kept for a retry
    e.tick(e._dirty_at + 1.0)
    assert len(tries) == 2 and e._dirty_at is None
