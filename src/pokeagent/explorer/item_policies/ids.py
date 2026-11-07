"""Item ids (Gen 1 / pokered) and display names."""
from __future__ import annotations

BICYCLE, MOON_STONE, ESCAPE_ROPE, REPEL = 0x06, 0x0A, 0x1D, 0x1E
FIRE_STONE, THUNDERSTONE, WATER_STONE = 0x20, 0x21, 0x22
HP_UP, PROTEIN, IRON, CARBOS, CALCIUM, RARE_CANDY = 0x23, 0x24, 0x25, 0x26, 0x27, 0x28
X_ACCURACY, LEAF_STONE, CARD_KEY = 0x2E, 0x2F, 0x30
SUPER_REPEL, MAX_REPEL = 0x38, 0x39
X_ATTACK, X_DEFEND, X_SPEED, X_SPECIAL = 0x41, 0x42, 0x43, 0x44
SILPH_SCOPE, POKE_FLUTE = 0x48, 0x49
HM01, TM01 = 0xC4, 0xC9

VITAMIN_STAT = {HP_UP: 0, PROTEIN: 1, IRON: 2, CARBOS: 3, CALCIUM: 4}  # index into PartyMon.stat_exp (hp atk def spd spc)
STONES = {MOON_STONE: "MOON STONE", FIRE_STONE: "FIRE STONE", THUNDERSTONE: "THUNDERSTONE", WATER_STONE: "WATER STONE", LEAF_STONE: "LEAF STONE"}
REPELS = (REPEL, SUPER_REPEL, MAX_REPEL)
X_ITEMS = {X_ATTACK: "X ATTACK", X_DEFEND: "X DEFEND", X_SPEED: "X SPEED", X_SPECIAL: "X SPECIAL"}
HM_BY_TAG = {"cut": HM01, "surf": HM01 + 2, "strength": HM01 + 3, "flash": HM01 + 4}  # HM01 CUT, 02 FLY, 03 SURF, 04 STRENGTH, 05 FLASH
HM_MOVE = {"cut": "CUT", "surf": "SURF", "strength": "STRENGTH", "flash": "FLASH"}
NAMES = {BICYCLE: "BICYCLE", RARE_CANDY: "RARE CANDY", HP_UP: "HP UP", PROTEIN: "PROTEIN", IRON: "IRON", CARBOS: "CARBOS",
         CALCIUM: "CALCIUM", REPEL: "REPEL", SUPER_REPEL: "SUPER REPEL", MAX_REPEL: "MAX REPEL", CARD_KEY: "CARD KEY",
         SILPH_SCOPE: "SILPH SCOPE", POKE_FLUTE: "POKe FLUTE", **STONES, **X_ITEMS,
         **{HM01 + k: f"HM{k + 1:02d}" for k in range(5)}, **{TM01 + k: f"TM{k + 1:02d}" for k in range(50)}}


def name_of(item_id: int) -> str:
    return NAMES.get(item_id, f"item 0x{item_id:02X}")


def is_hm(item_id: int) -> bool:
    return HM01 <= item_id < TM01


def is_tm(item_id: int) -> bool:
    return TM01 <= item_id < TM01 + 50
