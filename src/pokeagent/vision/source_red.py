"""The Pokemon Red label source: sprite table plus visible background map, read through Emulator."""
from __future__ import annotations

from pokeagent.ram_symbols import IS_IN_BATTLE
from pokeagent.vision.bgmap import LCDC_MAP, MAP_LEN, visible_cells
from pokeagent.vision.labels import FrameLabels, SpriteBox

# work RAM (pret/pokered wram.asm names; same addresses anomaly_sprites.py and ram.py use)
SPRITE_STATE1 = 0xC100    # wSpriteStateData1: +0 picture id (0 = empty), +2 image index (0xFF = hidden)
SPRITE_STATE2 = 0xC200    # wSpriteStateData2: +4 map y + 4, +5 map x + 4, +6 movement byte (UNVERIFIED, raw)
SLOT_LEN, SLOTS = 16, 16  # slot 0 is the player, 1-15 NPCs
HIDDEN = 0xFF
BALL_PIC = 61             # pick-up ball picture id (src/pokeagent/atlas/overlay.py)
MAP_ID, PLAYER_Y, PLAYER_X = 0xD35E, 0xD361, 0xD362
TILESET = 0xD367          # wCurMapTileset
# hardware registers
LCDC, SCY, SCX = 0xFF40, 0xFF42, 0xFF43
BG_MAP0, BG_MAP1 = 0x9800, 0x9C00
# the player sprite's top-left on screen in this game; an NPC one map tile away is 16 px away
PLAYER_X_PX, PLAYER_Y_PX, TILE_PX = 64, 60, 16
SCREEN_W, SCREEN_H = 160, 144


def _slot(emu, i: int) -> tuple[int, int, int, int, int]:
    """(pic, image index, map x, map y, move byte) of slot i, raw reads minus the +4 coord bias."""
    pic = emu.read(SPRITE_STATE1 + SLOT_LEN * i)
    img = emu.read(SPRITE_STATE1 + SLOT_LEN * i + 2)
    x = emu.read(SPRITE_STATE2 + SLOT_LEN * i + 5) - 4
    y = emu.read(SPRITE_STATE2 + SLOT_LEN * i + 4) - 4
    return pic, img, x, y, emu.read(SPRITE_STATE2 + SLOT_LEN * i + 6)


class RedSource:
    """Labels Red frames: sprite-table boxes (player + NPCs), background cells minus sprite overlaps."""

    name = "pokemon-red"
    boot_presses: tuple = ()   # reaching play needs the ~140-press intro; the tool takes --state

    def read(self, emu) -> FrameLabels:
        map_id = emu.read(MAP_ID)
        player = (emu.read(PLAYER_X), emu.read(PLAYER_Y))
        area, bank = f"map-{map_id}", emu.read(TILESET)
        cell = f"{player[0] // 4},{player[1] // 4}"
        if emu.read(IS_IN_BATTLE):
            return FrameLabels(area, bank, player, cell, skip=True)
        slots = [_slot(emu, i) for i in range(SLOTS)]
        sane = [(i, s) for i, s in enumerate(slots) if s[0] and s[1] != HIDDEN and s[2] >= 0 and s[3] >= 0]
        if not sane:            # the sprite table is cleared off the overworld (boot, fades, menus)
            return FrameLabels(area, bank, player, cell, skip=True)
        sprites = []
        for i, (pic, _img, nx, ny, move) in sane:
            x, y = PLAYER_X_PX + (nx - player[0]) * TILE_PX, PLAYER_Y_PX + (ny - player[1]) * TILE_PX
            if x + TILE_PX <= 0 or x >= SCREEN_W or y + TILE_PX <= 0 or y >= SCREEN_H:
                continue
            coarse = "player" if i == 0 else ("item" if pic == BALL_PIC else "npc")
            sprites.append(SpriteBox(pic, coarse, x, y, TILE_PX, TILE_PX, f"slot{i}", move, (nx, ny)))
        lcdc = emu.read(LCDC)
        bg = emu.read_range(BG_MAP1 if lcdc & LCDC_MAP else BG_MAP0, MAP_LEN)
        boxes = [(s.x, s.y) for s in sprites]
        tiles = [c for c in visible_cells(bg, emu.read(SCX), emu.read(SCY))
                 if not any(c.x < bx + TILE_PX and bx < c.x + 8 and c.y < by + TILE_PX and by < c.y + 8
                            for bx, by in boxes)]
        return FrameLabels(area, bank, player, cell, tuple(sprites), tuple(tiles))


SOURCE = RedSource()
