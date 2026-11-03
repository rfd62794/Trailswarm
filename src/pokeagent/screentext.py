"""Decode Pokemon Red text bytes and the visible 20x18 tile-map mirror.

The charmap below was VERIFIED on the real ROM on 2026-11-02 for A-Z, a-z, 0-9, space, 0xBA (é)
and 0xED (the menu cursor); the remaining punctuation entries are from memory of pret/pokered:
unknown bytes decode to ``?`` in text, and non-glyph tile ids decode to ``.``
on screen so overworld graphics show as dots while dialog shows as words.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokeagent.emulator import Emulator
    from pokeagent.names import Registry

END_MARKER = 0x50
SCREEN_ROWS = 18
SCREEN_COLS = 20

CHARMAP: dict[int, str] = {
    0x7F: " ",
    0x50: "",  # end-of-string marker (decode_text stops here anyway)
    0x4E: "\n",
    0x4F: "\n",
    0x51: "\n",  # prompt/para markers render as line breaks
    0x55: "\n",
    0x57: "\n",
    0x58: "\n",
    0xE1: "PK",
    0xE2: "MN",
    0xE3: "-",
    0xE6: "?",
    0xE7: "!",
    0xE8: ".",
    0xEF: "(M)",  # male sign; ASCII so cp1252 consoles never crash on print
    0xF0: "¥",
    0xF1: "x",
    0xF3: "/",
    0xF4: ",",
    0xF5: "(F)",  # female sign
    0xBA: "é",    # verified: POKéMON in the START menu
    0xED: ">",    # verified: the menu cursor
}
CHARMAP.update({0x80 + i: chr(ord("A") + i) for i in range(26)})
CHARMAP.update({0xA0 + i: chr(ord("a") + i) for i in range(26)})
CHARMAP.update({0xF6 + i: str(i) for i in range(10)})

# Tile ids that render as visible glyphs; control codes and graphics are not here.
_TILE_TEXT = {b: s for b, s in CHARMAP.items() if s and s != "\n"}


def decode_text(raw: bytes) -> str:
    """Decode a text byte string, stopping at the 0x50 end marker."""
    out: list[str] = []
    for b in raw:
        if b == END_MARKER:
            break
        out.append(CHARMAP.get(b, "?"))
    return "".join(out)


def _tile_char(b: int) -> str:
    """One tile-map byte as a screen char: glyph, blank, or '.' for graphics."""
    if b == 0x00:
        return " "  # blank tile
    return _TILE_TEXT.get(b, ".")


def read_screen_text(emu: Emulator, registry: Registry) -> list[str]:
    """The 18x20 visible tile map at wTileMap as text rows.

    Rows are right-stripped and rows holding only blanks are dropped, so an
    empty tile map returns []. Map graphics decode to '.', dialog to words.
    """
    entry = registry.by_name["wTileMap"]
    raw = emu.read_range(entry.addr, entry.size)
    rows: list[str] = []
    for r in range(SCREEN_ROWS):
        line = "".join(
            _tile_char(b) for b in raw[r * SCREEN_COLS : (r + 1) * SCREEN_COLS]
        ).rstrip()
        if line:
            rows.append(line)
    return rows
