"""Tile-type learning: which 2x2 tile-id blocks are solid, per tileset, so a bookshelf is never bumped twice.

Mixed into MapMemory. The ROM collision data (``rom_walkable`` / ``rom_pairs``, wired by the demo from atlas.collision) always
wins over learning: a stepping tile in the walkable list is never learned solid, and a tile PAIR the ROM blocks (cave
elevation steps: stand on 0x05, step to 0x20) is solid for that edge although both tiles are walkable.
"""
from __future__ import annotations


class TilesMixin:
    def rom_pair_blocked(self, tileset: int, ahead: list[int], stand: int | None) -> bool:
        """The ROM's tile-pair table blocks the edge from the stood-on tile to the stepping tile (either order)."""
        pairs = self.rom_pairs(tileset) if self.rom_pairs else None
        return bool(pairs) and stand is not None and len(ahead) > 2 and (stand, ahead[2]) in pairs

    def rom_says_walkable(self, tileset: int, ahead: list[int], stand: int | None = None) -> bool:
        """The stepping tile (bottom-left of the 2x2 ahead) is in the ROM collision list and not pair-blocked from ``stand``:
        learning may never call it solid."""
        ids = self.rom_walkable(tileset) if self.rom_walkable else None
        return bool(ids) and len(ahead) > 2 and ahead[2] in ids and not self.rom_pair_blocked(tileset, ahead, stand)

    def learn_tiles(self, tileset: int, ahead: list[int], walkable: bool, stand: int | None = None):
        if not walkable and (self.rom_says_walkable(tileset, ahead, stand) or self.rom_pair_blocked(tileset, ahead, stand)):
            return  # a person/page/fade made it fail, or the ROM pair table already explains it: not a property of the ahead tile
        t = self.data.setdefault("tile_types", {}).setdefault(str(tileset), {})
        key = ",".join(f"{b:02X}" for b in ahead)
        e = t.setdefault(key, {"solid": 0, "walkable": 0})
        e["walkable" if walkable else "solid"] += 1

    def known_solid(self, tileset: int, ahead: list[int], stand: int | None = None) -> bool:
        if self.rom_pair_blocked(tileset, ahead, stand):
            return True  # blocked by the ROM pair table from where we stand
        if self.rom_says_walkable(tileset, ahead, stand):
            return False  # learned 'solid' never overrides the ROM tileset collision data (Mt Moon B1F, 2026-11-05)
        e = self.data.get("tile_types", {}).get(str(tileset), {}).get(",".join(f"{b:02X}" for b in ahead))
        return bool(e) and e["solid"] >= 3 and e["walkable"] == 0
