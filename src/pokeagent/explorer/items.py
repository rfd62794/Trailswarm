"""Item balls: picture id 61 is the Poke Ball sprite - the world's item markers.

Verified from the shared ``runs/maps.json`` sprite table on 2026-11-05 (slot ``pic`` at
``0xC1x0``, position from ``0xC2x4/5`` minus 4, as ``MapMemory.observe_npcs`` records it):
pic 61 marks the three starter balls in Oak's lab and the item balls on Route 2 and in
Viridian Forest. A picked-up ball's slot drops to pic 0 / leaves the map, so "still there"
is always a live sprite-table read, never memory.
"""
from __future__ import annotations

import re

BALL_PIC = 61

# wSpriteStateData1 0xC100 / wSpriteStateData2 0xC200, 16 slots x 16 bytes (ram_names.json):
# Data1 +0 picture id, +1 movement status; Data2 +4 map y+4, +5 map x+4. Slot 0 is the player.
_SPRITES1, _SPRITES2 = 0xC100, 0xC200
_SLOTS = range(1, 16)
_MOVING = 0xF0  # movement-status high nibble: nonzero means a movement is in progress

_FOUND_ITEM = re.compile(r"(?:found|obtained)\s+(.+?)(?:!|$)", re.IGNORECASE)


def item_balls(emu) -> list[tuple[int, int, int]]:
    """``(slot, x, y)`` of every item ball live in the sprite table: pic BALL_PIC, stationary,
    reporting an on-map position. A sprite mid-move or with no map position is skipped."""
    out = []
    for i in _SLOTS:
        d1 = _SPRITES1 + 16 * i
        if emu.read(d1) != BALL_PIC or emu.read(d1 + 1) & _MOVING:
            continue
        x = emu.read(_SPRITES2 + 16 * i + 5) - 4
        y = emu.read(_SPRITES2 + 16 * i + 4) - 4
        if x < 0 or y < 0:
            continue
        out.append((i, x, y))
    return out


def is_item_ball(npc_entry: dict | None) -> bool:
    """A sprite-table memory entry is an item ball: pic BALL_PIC and never seen moving."""
    return bool(npc_entry) and npc_entry.get("pic") == BALL_PIC and not npc_entry.get("moves")


def parse_item_text(text: str) -> str | None:
    """The item name from a "... found ITEM!" / "... obtained ITEM!" dialog, else None."""
    m = _FOUND_ITEM.search(text or "")
    return m.group(1).strip() if m else None
