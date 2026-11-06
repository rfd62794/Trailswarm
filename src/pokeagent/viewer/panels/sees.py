"""Sees panel: the agent's tile map (or battle view) as coloured glyph rows, plus the legend line.

Glyph -> kind colours come from ``pokeagent.explorer.legend`` (imported, not re-implemented);
rows that are not pure glyph rows (the legend text, battle text, box text) render dim/plain.
"""
from __future__ import annotations

from pokeagent.explorer import legend
from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.panels import DIM, TEXT, Line, plain

# One colour per world-legend kind; ledge jump directions share the ledge colour.
_KIND_COLORS = {
    "you": "#ffd166", "npc": "#9fd8ff", "trainer": "#ff9f7f", "trainer_beaten": "#86c98f",
    "wall": "#565b66", "object": "#c9a0dc", "grass": "#5fa85f", "encounter": "#ff6b6b",
    "ledge": "#e0c060", "warp": "#5a8fd6", "interaction": "#8fd0c0",
    "walkable": "#3f444e", "unknown": "#6a707c",
}
_CHAR_COLOR: dict[str, str] = {}
for _kind, _glyph in legend.GLYPHS.items():
    if len(_glyph) == 1:
        _CHAR_COLOR[_glyph] = _KIND_COLORS[_kind]
for _ch in legend.LEDGE_GLYPH.values():
    _CHAR_COLOR.setdefault(_ch, _KIND_COLORS["ledge"])
GLYPH_CHARS = frozenset(_CHAR_COLOR)


def _glyph_line(row: str) -> Line:
    return [(ch, _CHAR_COLOR.get(ch, DIM)) for ch in row]


def sees_lines(snap: AgentSnapshot) -> list[Line]:
    """Rows + legend line. Battle mode renders its text rows plainly; overworld/menu rows get
    per-glyph colours. A row qualifies for glyph colouring only when every char is a legend glyph."""
    rows = list(snap.sees.rows or [])
    if not rows:
        return [plain("(no vision)", DIM)]
    battle = snap.sees.mode == "battle"
    out: list[Line] = []
    for row in rows:
        if not battle and row and all(ch in GLYPH_CHARS for ch in row):
            out.append(_glyph_line(row))
        else:
            out.append(plain(row, TEXT if battle else DIM))
    return out
