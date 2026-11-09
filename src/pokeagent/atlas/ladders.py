"""ladders: the warp tiles a map's ROM header lists toward a destination map (for explorer.cave_route)."""
from __future__ import annotations

from pokeagent.atlas import rom_maps
from pokeagent.game.pokemon_red import RED

# str signature default, forward slashes on every OS; RED-pinned: fixed at def time, POKEAGENT_GAME must not change it
_DEFAULT_ROM = str(RED.default_rom).replace("\\", "/")

LAST_MAP = 0xFF  # a warp's destination byte for "the map we came from" (a cave mouth)
ROUTE4 = 0x0F    # asking for Route 4 also matches the "back outside" warps


def rom_ladders(rom_path: str = _DEFAULT_ROM):
    """A ``(map_id, dest_map) -> [(x, y)]`` lookup over the ROM's map headers; None when the ROM is unreadable."""
    try:
        rom = rom_maps.load(rom_path)
    except OSError:
        return None

    def ladders(map_id: int, dest_map: int, near: tuple | None = None) -> list[tuple[int, int]]:
        """Warp tiles on ``map_id`` leading to ``dest_map``. With ``near`` = (x, y) on the destination map, only the one
        whose LANDING tile (the destination map's warp the header points at) is closest to it: a floor can be split into
        regions, and the ladder that lands beside the exit is the one that leads out (Mt Moon B2F (5,7) -> B1F (23,3))."""
        warps = rom_maps.header(rom, map_id).warps
        hits = [(x, y, dw) for x, y, dw, dm in warps if dm == dest_map or (dest_map == ROUTE4 and dm == LAST_MAP)]
        if near is None or dest_map in (ROUTE4, LAST_MAP):
            return [(x, y) for x, y, _dw in hits]
        dest_warps = rom_maps.header(rom, dest_map).warps

        def landing_gap(h: tuple) -> int:
            lx, ly = (dest_warps[h[2]][0], dest_warps[h[2]][1]) if h[2] < len(dest_warps) else (999, 999)
            return abs(lx - near[0]) + abs(ly - near[1])
        return [(x, y) for x, y, _dw in sorted(hits, key=landing_gap)[:1]]
    return ladders
