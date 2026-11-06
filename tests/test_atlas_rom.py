"""Atlas acceptance against the real ROM (skipped when roms/Pokemon Red.gb is absent)."""
from __future__ import annotations

from pathlib import Path

import pytest

from pokeagent.atlas import rom_maps as R
from pokeagent.atlas import tiles
from pokeagent.atlas.render import render_map
from pokeagent.atlas.world import build_layout

ROM = Path(__file__).resolve().parents[1] / "roms" / "Pokemon Red.gb"
pytestmark = pytest.mark.skipif(not ROM.exists(), reason="ROM not present")


@pytest.fixture(scope="module")
def rom():
    return ROM.read_bytes()


def test_pallet_renders_and_warps_match_header(rom):
    hd = R.header(rom, 0)
    assert (hd.w * 2, hd.h * 2) == (20, 18)                         # cells; 10x9 blocks = 320x288 px
    assert sorted((x, y) for x, y, _, _ in hd.warps) == [(5, 5), (12, 11), (13, 5)]
    img = render_map(rom, hd, tiles.load_tileset(rom, hd.tileset))
    assert img.shape == (288, 320, 3) and len({tuple(p) for p in img.reshape(-1, 3)}) > 2


def test_route1_north_of_pallet_and_viridian_north_of_route1(rom):
    lay = build_layout(R.all_headers(rom))
    pal, r1, vir = lay.places[0], lay.places[0x0C], lay.places[1]
    assert (r1.x, r1.y + r1.h) == (pal.x, pal.y)                    # directly north, same x
    assert vir.y + vir.h == r1.y and vir.x == r1.x - 10             # offset -5 blocks = 10 cells
    assert len([p for p in lay.places.values() if not p.interior]) == 36
