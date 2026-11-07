"""Reads for the anomaly detectors: the sprite table and the doorway tiles of a map (pure, cheap)."""
from __future__ import annotations

from pokeagent.explorer.perceive import DIRS

SPRITE_STATE1 = 0xC100   # wSpriteStateData1: 16 bytes per slot, slot 0 is the player; +0 picture id, +2 image index (0xFF = hidden)
SPRITE_STATE2 = 0xC200   # wSpriteStateData2: +4 map y + 4, +5 map x + 4 (the offsets observe_npcs already uses)
SPRITE_SLOTS = range(1, 16)
HIDDEN = 0xFF


def read_sprites(emu) -> dict[int, tuple[int, int, int]]:
    """{slot: (picture id, x, y)} for every visible non-player sprite, in map tile coordinates."""
    out = {}
    for i in SPRITE_SLOTS:
        pic = emu.read(SPRITE_STATE1 + 16 * i)
        if not pic or emu.read(SPRITE_STATE1 + 16 * i + 2) == HIDDEN:
            continue
        out[i] = (pic, emu.read(SPRITE_STATE2 + 16 * i + 5) - 4, emu.read(SPRITE_STATE2 + 16 * i + 4) - 4)
    return out


def doorway_tiles(warps: dict) -> set[tuple[int, int]]:
    """Tiles that count as a doorway: a learned warp key is 'x,y,DIR' (stand on x,y, press DIR); both x,y and the
    tile DIR leads onto are the door."""
    out = set()
    for key in warps:
        try:
            x, y, d = key.split(",")
            dx, dy = DIRS[d]
            out.add((int(x), int(y)))
            out.add((int(x) + dx, int(y) + dy))
        except (ValueError, KeyError):
            continue
    return out


def wanderer_slots(npcs: dict) -> set[int]:
    """Slots of NPCs that have been seen on more than one tile (memory: npcs['slotN:picP']['moves'])."""
    return {e["slot"] for e in npcs.values() if e.get("moves") and "slot" in e}


def walkable_tiles(map_data: dict) -> set[tuple[int, int]]:
    """Tiles known to be standable: visited ones plus every tile any NPC was ever seen on."""
    out = set()
    for k in map_data.get("visited", {}):
        x, y = k.split(",")
        out.add((int(x), int(y)))
    for e in map_data.get("npcs", {}).values():
        for k in e.get("positions", {}):
            x, y = k.split(",")
            out.add((int(x), int(y)))
    return out
