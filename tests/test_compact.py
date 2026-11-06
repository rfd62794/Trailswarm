"""Compact inset grid (only unanchored interiors), default mode + saved preference, no outdoor dimming."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pokeagent.atlas import anchor, fit, inplace, inplace_render
from pokeagent.atlas.compact import OFF, compact_image, compact_layout, in_grid
from pokeagent.atlas.overrides import Overrides
from pokeagent.atlas.world import CELL
from conftest import walkgrid, world

ROM = Path("roms/Pokemon Red.gb")


def anchored():
    H, L = world()
    a = anchor.anchor_interiors(H, L)
    return H, L, a, {m for m, p in L.places.items() if p.interior} - set(a)


def test_compact_grid_keeps_only_unanchored_and_shrinks():
    H, L, a, keep = anchored()
    assert keep == {13, 14}                                                  # 13 is only reachable by a learned warp
    C = compact_layout(L, keep)
    assert in_grid(C, 14) and in_grid(C, 13) and not any(in_grid(C, m) for m in a)
    assert C.places[10].w == L.places[10].w and C.places[10].x == OFF       # size kept for in-place use, but not in the grid
    assert C.height < L.height and C.height == max(C.places[m].y + C.places[m].h for m in (13, 14)) + 2
    assert all(C.places[m] == L.places[m] for m, p in L.places.items() if not p.interior)
    assert compact_layout(L, set()).height == L.outdoor_height              # nothing unanchored: no grid at all
    assert in_grid(L, 10)                                                    # the full layout (inset mode) is untouched


def test_compact_image_copies_outdoor_and_kept_tiles():
    H, L, a, keep = anchored()
    base = np.zeros((L.height * CELL, L.width * CELL, 3), np.uint8)
    base[:L.outdoor_height * CELL] = 77
    p = L.places[14]
    base[p.y * CELL:(p.y + p.h) * CELL, p.x * CELL:(p.x + p.w) * CELL] = 200
    C = compact_layout(L, keep)
    img = compact_image(base, L, C, keep)
    assert img.shape == (C.height * CELL, C.width * CELL, 3)
    assert (img[:C.outdoor_height * CELL] == 77).all()
    q = C.places[14]
    assert (img[q.y * CELL:(q.y + q.h) * CELL, q.x * CELL:(q.x + q.w) * CELL] == 200).all()


def test_in_place_mode_never_dims_the_outdoor_map():
    H, L, a, keep = anchored()
    wk = walkgrid(10, 10)
    xf = fit.build_xforms(a, L, lambda m: wk, False)
    vl = inplace.view_layout(L, a, xf, {10})
    base = np.full((L.height * CELL, L.width * CELL, 3), 100, np.uint8)
    imgs = SimpleNamespace(get=lambda m: np.full((L.places[m].h * CELL, L.places[m].w * CELL, 3), 200, np.uint8))
    out = inplace_render.compose(base, vl, a, {10}, imgs)
    t, p = xf[10], L.places[10]
    x0, y0, x1, y1 = (int(t.ox * CELL), int(t.oy * CELL), int((t.ox + p.w) * CELL), int((t.oy + p.h) * CELL))
    mask = np.ones(base.shape[:2], bool)
    mask[max(0, y0 - 2):y1 + 12, max(0, x0 - 2):x1 + 12] = False                 # the interior, its frame and its shadow
    assert (out[mask] == 100).all()                                              # everything else is exactly as rendered
    assert (out[y1 + 2:y1 + 4, x0 + 10:x1 - 10] < 100).all()                      # the shadow is there


def test_default_mode_is_the_original_inset_and_the_choice_persists(tmp_path, monkeypatch):
    from pokeagent.viewer.ui import world_interiors as wi
    assert inplace.DEFAULT_MODE == "inset"
    u = tmp_path / "u.json"
    view = SimpleNamespace(world=None, wm=SimpleNamespace(rev=0))
    real = Overrides.load
    monkeypatch.setattr(wi.Overrides, "load", staticmethod(lambda *a, **k: real(u, None)))
    layer = wi.InteriorLayer(view)
    assert layer.mode == "inset"                                                  # nobody chose anything: the original atlas
    layer.set_mode("inplace")
    layer.edit.flush()
    assert json.loads(u.read_text())["prefs"] == {"mode": "inplace"}
    assert wi.InteriorLayer(view).mode == "inplace"                               # picking fit sticks across restarts
    layer.set_mode("inset")
    layer.edit.flush()
    assert wi.InteriorLayer(view).mode == "inset"


def test_saved_mode_ignores_junk(tmp_path):
    u = tmp_path / "u.json"
    for body in ({"prefs": {"mode": "sideways"}}, {"prefs": 5}, {"prefs": {"mode": 3}}):
        u.write_text(json.dumps(body))
        assert Overrides.load(u, None).mode is None
    ov = Overrides()
    ov.set_mode("bogus")
    assert ov.mode is None


def test_world_variant_kinds():
    from pokeagent.viewer.ui.world_stretch import kind_for, kind_of
    assert [kind_for(m) for m in ("inset", "auto", "inplace", "inplace_full", "stretch")] == ["full", "compact", "compact", "compact", "stretch"]
    H, L = world()
    w = SimpleNamespace(layout=L, compact=False)
    assert kind_of(w) == "full" and kind_of(SimpleNamespace(layout=L, compact=True)) == "compact"
    assert kind_of(SimpleNamespace(layout=SimpleNamespace(warp=object()), compact=True)) == "stretch"


@pytest.mark.skipif(not ROM.exists(), reason="no ROM")
def test_real_rom_compact_grid_holds_only_the_six():
    from pokeagent.atlas.rom_maps import all_headers, load
    from pokeagent.atlas.world import build_layout
    from pokeagent.world.export import World, compact_world, full_world
    from pokeagent.world.draw import SpriteBook
    rom = load(ROM)
    H = all_headers(rom)
    L = build_layout(H)
    w = World(rom, H, L, np.zeros((16, 16, 3), np.uint8), SpriteBook(rom))
    keep = {m for m, p in L.places.items() if p.interior} - set(inplace.usable_anchors(H, L))
    C = compact_layout(L, keep)
    assert len(keep) == 6 and sum(in_grid(C, m) for m in C.places) == 6
    assert C.height < L.height * 0.6 and C.height - C.outdoor_height < 40               # no empty space below the world
    assert full_world(w) is w


def test_viewer_opens_on_the_full_world_by_default(monkeypatch, tmp_path):
    from pokeagent.world import export
    seen = []
    w = SimpleNamespace(compact=False)
    monkeypatch.setattr(export, "load_world", lambda *a, **k: w)
    monkeypatch.setattr(export, "compact_world", lambda *a, **k: seen.append("compact") or "compact-world")
    real = Overrides.load
    monkeypatch.setattr(export.Overrides, "load", staticmethod(lambda *a, **k: real(tmp_path / "none.json", None)))
    assert export.load_for_view() is w and seen == []                      # no saved choice: the full inset world
    (tmp_path / "p.json").write_text(json.dumps({"prefs": {"mode": "inplace"}}))
    monkeypatch.setattr(export.Overrides, "load", staticmethod(lambda *a, **k: real(tmp_path / "p.json", None)))
    assert export.load_for_view() == "compact-world" and seen == ["compact"]   # picked fit earlier: compact world
