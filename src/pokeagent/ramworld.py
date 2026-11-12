"""Typed decoders for non-mon RAM: badges, Pokedex, play time, map header, menu/text, event flags."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from pokeagent.emulator import Emulator
from pokeagent.ram import decode_bcd
from pokeagent.ram_symbols import MENU_ITEM

BADGES, MONEY = 0xD356, 0xD347
POKEDEX_OWNED, POKEDEX_SEEN, POKEDEX_BYTES = 0xD2F7, 0xD30A, 19
PLAY_TIME = 0xDA41           # hours, maxed flag, minutes, seconds, frames
MAP_HEADER = 0xD367          # tileset, height, width, data ptr, text ptr, script ptr, connections
NUM_WARPS, WARP_ENTRIES = 0xD3AE, 0xD3AF
NUM_SIGNS, SIGN_COORDS = 0xD4B0, 0xD4B1
NUM_SPRITES, MAP_SPRITE_DATA = 0xD4E1, 0xD4E4
TOP_MENU_Y, TOP_MENU_X, MAX_MENU_ITEM, TEXT_BOX_ID = 0xCC24, 0xCC25, 0xCC28, 0xD125
EVENT_FLAGS, EVENT_FLAG_BYTES = 0xD747, 320
BADGE_NAMES = ("boulder", "cascade", "thunder", "rainbow", "soul", "marsh", "volcano", "earth")


def bit_indices(raw: bytes) -> list[int]:
    """Indices of the set bits, LSB first within each byte (Pokedex / event flag convention)."""
    return [i for i in range(len(raw) * 8) if raw[i // 8] & (1 << (i % 8))]


def read_money(emu: Emulator) -> int:
    return decode_bcd(emu.read_range(MONEY, 3))


def read_badges(emu: Emulator) -> list[str]:
    """Names of the badges held (wObtainedBadges bit 0 = Boulder)."""
    return [BADGE_NAMES[i] for i in bit_indices(bytes([emu.read(BADGES)]))]


def read_pokedex(emu: Emulator) -> tuple[list[int], list[int]]:
    """(owned, seen) as lists of Pokedex numbers (1-151)."""
    owned = bit_indices(emu.read_range(POKEDEX_OWNED, POKEDEX_BYTES))
    seen = bit_indices(emu.read_range(POKEDEX_SEEN, POKEDEX_BYTES))
    return [i + 1 for i in owned if i < 151], [i + 1 for i in seen if i < 151]


@dataclass(frozen=True)
class PlayTime:
    hours: int
    maxed: bool
    minutes: int
    seconds: int
    frames: int

    def __str__(self) -> str:
        return f"{self.hours}:{self.minutes:02d}:{self.seconds:02d}"


def read_play_time(emu: Emulator) -> PlayTime:
    h, maxed, m, s, f = emu.read_range(PLAY_TIME, 5)
    return PlayTime(h, bool(maxed), m, s, f)


@dataclass(frozen=True)
class Warp:
    y: int
    x: int
    dest_warp: int
    dest_map: int


@dataclass(frozen=True)
class MapHeader:
    tileset: int
    height: int         # in 2x2-tile blocks
    width: int
    warps: tuple[Warp, ...]
    signs: tuple[tuple[int, int], ...]          # (y, x)
    sprites: tuple[tuple[int, int], ...]        # (movement byte, text/trainer id) per NPC

    @property
    def tiles(self) -> tuple[int, int]:
        """(width, height) in walkable 2x2-tile cells: each map block is 2x2 cells (Pallet 10x9 -> 20x18)."""
        return self.width * 2, self.height * 2


def decode_map_header(head: bytes, warps: bytes, n_warps: int, signs: bytes, n_signs: int,
                      sprites: bytes, n_sprites: int) -> MapHeader:
    w = tuple(Warp(*warps[4 * i:4 * i + 4]) for i in range(min(n_warps, 32)))
    s = tuple((signs[2 * i], signs[2 * i + 1]) for i in range(min(n_signs, 16)))
    sp = tuple((sprites[2 * i], sprites[2 * i + 1]) for i in range(min(n_sprites, 16)))
    return MapHeader(tileset=head[0], height=head[1], width=head[2], warps=w, signs=s, sprites=sp)


def read_map_header(emu: Emulator) -> MapHeader:
    nw, ns, nsp = emu.read(NUM_WARPS), emu.read(NUM_SIGNS), emu.read(NUM_SPRITES)
    return decode_map_header(
        emu.read_range(MAP_HEADER, 3), emu.read_range(WARP_ENTRIES, 128), nw,
        emu.read_range(SIGN_COORDS, 32), ns, emu.read_range(MAP_SPRITE_DATA, 32), nsp)


@dataclass(frozen=True)
class MenuState:
    current_item: int
    max_item: int
    top_y: int
    top_x: int
    text_box_id: int


def read_menu(emu: Emulator) -> MenuState:
    return MenuState(emu.read(MENU_ITEM), emu.read(MAX_MENU_ITEM), emu.read(TOP_MENU_Y),
                     emu.read(TOP_MENU_X), emu.read(TEXT_BOX_ID))


def read_event_flags(emu: Emulator) -> bytes:
    return emu.read_range(EVENT_FLAGS, EVENT_FLAG_BYTES)


def event_flag(flags: bytes, index: int) -> bool:
    """Event flag by index (EVENT_* constant value): bit index%8 of byte index//8."""
    return bool(flags[index // 8] & (1 << (index % 8)))


def named_event_labels() -> dict[str, tuple[int, int]]:
    """pret's labelled WRAM near wEventFlags (D747-D886): name -> (addr, size). Few are named."""
    text = resources.files("pokeagent.data").joinpath("ram_map.json").read_text(encoding="utf-8")
    return {e["name"]: (int(e["addr"], 16), e["size"]) for e in json.loads(text)
            if EVENT_FLAGS <= int(e["addr"], 16) < EVENT_FLAGS + EVENT_FLAG_BYTES}
