"""Atlas: tile decode, block expansion, connection stitching, to_world, overlay drawing (all synthetic, no ROM)."""
from __future__ import annotations

import json

import numpy as np

from pokeagent.atlas import tiles
from pokeagent.atlas.agents_io import load_agents, read_agent
from pokeagent.atlas.overlay import CELL, Agent, overlay, warp_report
from pokeagent.atlas.render import render_blocks
from pokeagent.atlas.rom_maps import Connection, MapHeader
from pokeagent.atlas.world import Place, WorldLayout, build_layout, stitch


def _ts(blockset=None, tile_data=None) -> tiles.Tileset:
    return tiles.Tileset(0, blockset if blockset is not None else np.zeros((2, 4, 4), np.uint8),
                         tile_data if tile_data is not None else tiles.decode_tiles(b""))


def test_decode_tiles_planes_and_bit_order():
    # row 0: low plane 0b10000000, high plane 0b01000000 -> pixel0 = 1, pixel1 = 2; row 1: both set at pixel 7 -> 3
    raw = bytes([0x80, 0x40, 0x01, 0x01]) + bytes(12)
    t = tiles.decode_tiles(raw, 2)
    assert t.shape == (2, 8, 8)
    assert list(t[0, 0, :3]) == [1, 2, 0]
    assert t[0, 1, 7] == 3 and t[0, 1, 0] == 0
    assert not t[1].any()                       # tiles past the data stay blank


def test_decode_blockset_shape():
    raw = bytes(range(16)) + bytes(range(16, 32))
    b = tiles.decode_blockset(raw)
    assert b.shape == (2, 4, 4) and b[1, 0, 0] == 16 and b[0, 3, 3] == 15


def test_block_expansion_places_tiles_row_major():
    data = np.zeros((4, 8, 8), np.uint8)
    for i in range(4):
        data[i] = i                                    # tile i is a flat shade i
    bs = np.zeros((2, 4, 4), np.uint8)
    bs[1] = np.arange(16).reshape(4, 4) % 4           # block 1: tile ids cycle 0..3 along each row
    img = tiles.block_image(_ts(bs, data), 1)
    assert img.shape == (32, 32)
    assert img[0, 0] == 0 and img[0, 8] == 1 and img[0, 24] == 3 and img[8, 0] == 0 and img[8, 8] == 1


def test_render_blocks_border_pad_and_grey_palette():
    data = np.zeros((2, 8, 8), np.uint8)
    data[1] = 3                                        # tile 1 black
    bs = np.zeros((2, 4, 4), np.uint8)
    bs[1] = 1                                          # block 1 all black, block 0 white
    ts = _ts(bs, data)
    im = render_blocks(ts, bytes([0]), 1, 1, border=1, pad=1)
    assert im.shape == (96, 96, 3)
    assert im[48, 48, 0] == 255 and im[0, 0, 0] == 0   # centre = map block (white), ring = border (black)
    assert render_blocks(ts, bytes([1]), 1, 1).shape == (32, 32, 3)


def _hd(i, h, w, conns=()):
    return MapHeader(i, 0, h, w, 0, 0, list(conns))


def test_stitch_two_maps_north_and_offsets():
    # Route (10 wide, 18 high) with Town (20 wide, 18 high) to the north at offset -5, like Route 1 / Viridian.
    hs = {0: _hd(0, 18, 10, [Connection("N", 1, -5, 10)]), 1: _hd(1, 18, 20, [Connection("S", 0, 5, 10)])}
    pos = stitch(hs, 0)
    assert pos == {0: (0, 0), 1: (-5, -18)}


def test_stitch_all_directions():
    hs = {0: _hd(0, 4, 6, [Connection("S", 1, 2, 4), Connection("W", 2, -1, 4), Connection("E", 3, 1, 4)]),
          1: _hd(1, 3, 5), 2: _hd(2, 4, 3), 3: _hd(3, 4, 2)}
    pos = stitch(hs, 0)
    assert pos[1] == (2, 4) and pos[2] == (-3, -1) and pos[3] == (6, 1)


def test_layout_to_world_and_interior_inset_link():
    door = (3, 2, 0, 5)                                # warp at (x=3, y=2) leading to map 5
    hs = {0: MapHeader(0, 0, 2, 3, 0, 0, [Connection("E", 1, 0, 2)], [door]),
          1: _hd(1, 2, 2), 5: _hd(5, 1, 2)}
    lay = build_layout(hs)
    assert not lay.places[0].interior and not lay.places[1].interior
    assert lay.places[5].interior and lay.entrances[5] == (0, 3, 2)
    assert lay.places[5].y * CELL >= lay.outdoor_height * CELL      # insets sit below the stitched world
    assert lay.places[1].x == lay.places[0].x + 6                   # east neighbour is w*2 cells to the right
    p = lay.places[0]
    assert lay.to_world(0, 3, 2) == ((p.x + 3) * CELL, (p.y + 2) * CELL)
    assert lay.size_px == (lay.width * CELL, lay.height * CELL)


def _layout():
    return WorldLayout({0: Place(1, 1, 8, 8, False)}, 10, 10, 10)


def _base():
    return np.full((10 * CELL, 10 * CELL, 3), 255, np.uint8)


def _px(img, x, y):                                    # centre pixel of map-0 cell (x, y)
    return tuple(int(v) for v in img[(1 + y) * CELL + CELL // 2, (1 + x) * CELL + CELL // 2])


def test_overlay_returns_copy_and_draws_heat_and_agent():
    base = _base()
    model = {"maps": {"0": {"visited": {"2,3": 50, "3,3": 1}}}}
    out = overlay(base, _layout(), model, agents=[Agent("a", 0, 5, 5)], layers=("heat", "agents"))
    assert (base == 255).all()                                       # input untouched
    assert _px(out, 2, 3) != (255, 255, 255) and _px(out, 5, 5) != (255, 255, 255)
    assert _px(out, 2, 3)[1] < _px(out, 3, 3)[1]                     # hotter cell is redder (lower green)
    assert _px(out, 7, 7) == (255, 255, 255)


def test_overlay_walls_ledges_encounters_items():
    model = {"maps": {"0": {"blocked": ["2,2,UP"], "jumps": {"4,1,DOWN": [4, 3]}, "encounters": {"6,6": 9},
                           "npcs": {"s:pic61": {"pic": 61, "positions": {"1,6": 3}}}}}}
    out = overlay(_base(), _layout(), model, layers=("walls", "ledges", "encounters", "items"))
    assert tuple(out[1 * CELL + 2 * CELL, 1 * CELL + 2 * CELL + 5][:3]) == (200, 0, 200)   # top edge of cell (2,2)
    assert _px(out, 4, 2) == (0, 220, 255)                                                  # ledge arc between 4,1 and 4,3
    assert _px(out, 6, 6)[0] < 100 and _px(out, 1, 6)[2] == 0                               # green dot, yellow ball


def test_warp_report_and_disagreement_layer():
    hd = MapHeader(0, 0, 4, 4, 0, 0, warps=[(5, 5, 0, 9), (6, 1, 0, 9)])
    md = {"warps": {"5,6,UP": [9, 1, 1],           # target (5,5) is in the ROM: agree
                    "2,2,UP": [9, 1, 1],           # target (2,1) is not: false
                    "0,0,UP": [12, 0, 7]}}         # off the map edge: a connection, ignored
    rep = warp_report(md, hd, 8, 8)
    assert rep["agree"] == [(5, 5)] and rep["false"] == [(2, 1)] and rep["unlearned"] == [(6, 1)]
    out = overlay(_base(), _layout(), {"maps": {"0": md}}, {0: hd}, layers=("warps", "disagree"))
    assert _px(out, 2, 1)[0] == 255 and _px(out, 2, 1)[1] < 60                         # red = learned, not in ROM
    assert _px(out, 5, 5)[0] < 100 and _px(out, 5, 5)[2] > 200                         # blue = learned and in the ROM
    assert _px(out, 6, 1) == (255, 255, 255)           # hollow square: centre stays white


def test_trails_fade_and_skip_unplaced_maps(tmp_path):
    a = Agent("a", 0, 5, 5, [(0, 2, 2), (0, 3, 2), (99, 0, 0), (0, 4, 2)])
    out = overlay(_base(), _layout(), {}, agents=[a], layers=("trails",))
    older, newer = _px(out, 2, 2), _px(out, 4, 2)
    assert older != (255, 255, 255) and newer != (255, 255, 255) and sum(older) > sum(newer)   # older is fainter


def test_transitions_loader(tmp_path):
    d = tmp_path / "explore-20261105-212713-4242"
    d.mkdir()
    rows = [{"to": [0, 1, 1]}, {"to": [0, 1, 1]}, {"to": [0, 1, 2]}]
    (d / "transitions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n{partial", encoding="utf-8")
    a = read_agent(d / "transitions.jsonl", trail=5)
    assert (a.id, a.map, a.x, a.y) == ("4242", 0, 1, 2) and a.trail == [(0, 1, 1), (0, 1, 2)]
    reg = tmp_path / "agents"
    reg.mkdir()
    (reg / "explore-4242.json").write_text(json.dumps({"id": "explore-4242", "pid": 4242}), encoding="utf-8")
    assert load_agents([d / "transitions.jsonl"], reg)[0].id == "explore-4242"
    assert read_agent(tmp_path / "missing.jsonl") is None
