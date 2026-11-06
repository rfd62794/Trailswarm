"""ladders: the warp tiles a map's ROM header lists toward a destination map (for explorer.cave_route)."""
from __future__ import annotations

from pokeagent.atlas import rom_maps

LAST_MAP = 0xFF  # a warp's destination byte for "the map we came from" (a cave mouth)
ROUTE4 = 0x0F    # asking for Route 4 also matches the "back outside" warps


def rom_ladders(rom_path: str = "roms/Pokemon Red.gb"):
    """A ``(map_id, dest_map) -> [(x, y)]`` lookup over the ROM's map headers; None when the ROM is unreadable."""
    try:
        rom = rom_maps.load(rom_path)
    except OSError:
        return None

    def ladders(map_id: int, dest_map: int) -> list[tuple[int, int]]:
        return [(x, y) for x, y, _dw, dm in rom_maps.header(rom, map_id).warps
                if dm == dest_map or (dest_map == ROUTE4 and dm == LAST_MAP)]
    return ladders
