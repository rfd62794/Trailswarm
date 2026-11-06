"""Tile-type learning: which 2x2 tile-id blocks are solid, per tileset, so a bookshelf is never bumped twice.

Mixed into MapMemory. The ROM collision list (``rom_walkable``, wired by the demo from atlas.collision) always wins over learning.
"""
from __future__ import annotations


class TilesMixin:
    def rom_says_walkable(self, tileset: int, ahead: list[int]) -> bool:
        """The ROM collision list holds the stepping tile (bottom-left of the 2x2 ahead): learning may never call it solid."""
        ids = self.rom_walkable(tileset) if self.rom_walkable else None
        return bool(ids) and len(ahead) > 2 and ahead[2] in ids

    def learn_tiles(self, tileset: int, ahead: list[int], walkable: bool):
        if not walkable and self.rom_says_walkable(tileset, ahead):
            return  # a person, a page or a fade made the press fail: not a property of the tile
        t = self.data.setdefault("tile_types", {}).setdefault(str(tileset), {})
        key = ",".join(f"{b:02X}" for b in ahead)
        e = t.setdefault(key, {"solid": 0, "walkable": 0})
        e["walkable" if walkable else "solid"] += 1

    def known_solid(self, tileset: int, ahead: list[int]) -> bool:
        if self.rom_says_walkable(tileset, ahead):
            return False  # learned 'solid' never overrides the ROM tileset collision data (Mt Moon B1F, 2026-11-05)
        e = self.data.get("tile_types", {}).get(str(tileset), {}).get(",".join(f"{b:02X}" for b in ahead))
        return bool(e) and e["solid"] >= 3 and e["walkable"] == 0
