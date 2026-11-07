"""Item balls: picture id 61 is the Poke Ball sprite - the world's item markers.

Verified from the shared ``runs/maps.json`` sprite table on 2026-11-05 (slot ``pic`` at
``0xC1x0``, position from ``0xC2x4/5`` minus 4, as ``MapMemory.observe_npcs`` records it):
pic 61 marks the three starter balls in Oak's lab and the item balls on Route 2 and in
Viridian Forest. A picked-up ball keeps pic 61 and its position but its image index (0xC1x2) goes 0xFF,
so "still there" is always a live sprite-table read, never memory.
"""
from __future__ import annotations

import re

BALL_PIC = 61

# wSpriteStateData1 0xC100 / wSpriteStateData2 0xC200, 16 slots x 16 bytes (ram_names.json):
# Data1 +0 picture id, +2 image index; Data2 +4 map y+4, +5 map x+4, +6 movement byte. Slot 0 is the player.
# Verified on the ROM (Route 2 / Viridian Forest, 2026-11-05): a live ball reads movement status 1/2, image index
# 0x9C-0xAC while drawn and movement byte 0xFF (STAY; walkers are 0xFE). Gen 1's HideObject keeps pic 61 and the
# position and sets the image index to 0xFF, and the same 0xFF is what a sprite outside the screen reads - so
# "hidden" only counts for a ball inside the view window around the player. (Data1 +1 is a small state code
# 0/1/2/3, never a 0xF0 nibble, so it says nothing about "moving".)
_SPRITES1, _SPRITES2 = 0xC100, 0xC200
_SLOTS = range(1, 16)
_WALKING = 0xFE   # wSpriteStateData2 +6 movement byte: random walk; 0xFF is STAY (every item ball)
_HIDDEN = 0xFF    # wSpriteStateData1 +2 image index of a hidden / not-drawn sprite
VIEW = 4          # tiles around the player in which an 0xFF image index means hidden, not off screen
_PLAYER_Y, _PLAYER_X = 0xD361, 0xD362

_FOUND_ITEM = re.compile(r"(?:found|obtained)\s+(.+?)(?:!|$)", re.IGNORECASE)


def _balls(emu) -> list[tuple[int, int, int, int]]:
    """``(slot, x, y, image_index)`` of every static pic-BALL_PIC sprite that reports a map position."""
    out = []
    for i in _SLOTS:
        d1 = _SPRITES1 + 16 * i
        if emu.read(d1) != BALL_PIC or emu.read(_SPRITES2 + 16 * i + 6) == _WALKING:
            continue
        x = emu.read(_SPRITES2 + 16 * i + 5) - 4
        y = emu.read(_SPRITES2 + 16 * i + 4) - 4
        if x < 0 or y < 0:
            continue
        out.append((i, x, y, emu.read(d1 + 2)))
    return out


def _near(emu, x: int, y: int, within: int) -> bool:
    return max(abs(x - emu.read(_PLAYER_X)), abs(y - emu.read(_PLAYER_Y))) <= within


def item_balls(emu) -> list[tuple[int, int, int]]:
    """``(slot, x, y)`` of every item ball still live in the sprite table: pic BALL_PIC, standing still, on
    the map, and not hidden (image index 0xFF inside the view window = already collected)."""
    return [(i, x, y) for i, x, y, img in _balls(emu) if not (img == _HIDDEN and _near(emu, x, y, VIEW))]


def hidden_balls(emu, within: int = 2) -> list[tuple[int, int, int]]:
    """``(slot, x, y)`` of pic-61 sprites hidden (0xFF) within ``within`` tiles of the player: certainly
    collected this save (at that range the sprite would be drawn if it were live)."""
    return [(i, x, y) for i, x, y, img in _balls(emu) if img == _HIDDEN and _near(emu, x, y, within)]


def is_item_ball(npc_entry: dict | None) -> bool:
    """A sprite-table memory entry is an item ball: pic BALL_PIC and never seen moving."""
    return bool(npc_entry) and npc_entry.get("pic") == BALL_PIC and not npc_entry.get("moves")


def parse_item_text(text: str) -> str | None:
    """The item name from a "... found ITEM!" / "... obtained ITEM!" dialog, else None."""
    m = _FOUND_ITEM.search(text or "")
    name = re.sub(r"^[^A-Za-z0-9]+", "", m.group(1)).strip() if m else ""  # drop the box border / line break marks
    return name or None
