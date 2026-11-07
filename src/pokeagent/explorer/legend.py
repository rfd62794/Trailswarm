"""The world legend: one table of tile kinds and glyphs - the single source every renderer shares.

Sees (``perceive.ascii_vision``), Remembers (``MapMemory.render_memory``) and the viewer (V2 imports
``line``/``glyph`` for its legend line) all draw from this table. ``PRECEDENCE`` is the order
``tilekind.classify`` checks kinds in (the directive's ``@ T/t * N W ledge o # ! ~ i . ?``; ``you`` is
the renderer's own overlay and never returned by classify).
"""
from __future__ import annotations

# (kind, glyph, meaning) in the legend's display order.
KIND_ROWS = [
    ("you", "@", "the player"),
    ("npc", "N", "an NPC not known to battle"),
    ("trainer", "T", "an NPC that started a trainer battle"),
    ("trainer_beaten", "t", "a beaten trainer"),
    ("item", "*", "an item ball"),
    ("wall", "#", "terrain the player cannot enter"),
    ("object", "o", "solid tile with an interaction (sign, PC)"),
    ("grass", "~", "tile whose block id is in grass_ids"),
    ("encounter", "!", "grass tile where a wild battle started"),
    ("ledge", "v^<>", "a recorded one-way ledge jump (glyph = jump direction)"),
    ("warp", "W", "door/stairs/edge warp"),
    ("interaction", "i", "walkable spot with a recorded interaction"),
    ("walkable", ".", "visited / learned walkable"),
    ("unknown", "?", "never tried"),
]
GLYPHS = {kind: glyph_ for kind, glyph_, _ in KIND_ROWS}
MEANINGS = {kind: meaning for kind, _, meaning in KIND_ROWS}
PRECEDENCE = ("you", "trainer", "trainer_beaten", "item", "npc", "warp", "ledge", "object", "wall",
              "encounter", "grass", "interaction", "walkable", "unknown")
LEDGE_GLYPH = {"UP": "^", "DOWN": "v", "LEFT": "<", "RIGHT": ">"}


def glyph(kind: str, direction: str | None = None) -> str:
    """The character for a kind; a ledge picks its glyph from the jump direction."""
    if kind == "ledge":
        return LEDGE_GLYPH.get(direction or "", "?")
    return GLYPHS.get(kind, "?")


class Rendered(list):
    """A renderer's rows plus ``legend``: the ``line()`` string for the kinds the rows contain.

    A ``list`` subclass so ``"\\n".join(rows)`` and ``{"rows": rows}`` keep working unchanged while
    callers that want the legend read ``rows.legend``.
    """

    def __init__(self, rows=(), legend: str = "") -> None:
        super().__init__(rows)
        self.legend = legend


def line(kinds_present) -> str:
    """The legend string for the kinds a render contains, table order, present kinds only."""
    present = set(kinds_present)
    return "  ".join(f"{glyph_} {meaning}" for kind, glyph_, meaning in KIND_ROWS if kind in present)
