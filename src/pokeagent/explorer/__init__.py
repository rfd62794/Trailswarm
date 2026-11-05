"""The rule-based explorer, as a package (see docs/directives/Explorer_Behaviours_Directive.md).

Every name the old single-file ``pokeagent.explorer`` module exposed is re-exported here, so
``from pokeagent.explorer import Explorer, MapMemory, frame_lines`` keeps working unchanged.
"""
from __future__ import annotations

from pokeagent.explorer.legacy import Explorer
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.perceive import (
    BATTLE_FLAG,
    BORDER_TL,
    DIRS,
    TILEMAP_ADDR,
    TILEMAP_LEN,
    box_open,
    frame_lines,
    is_menu,
)

__all__ = [
    "BATTLE_FLAG", "BORDER_TL", "DIRS", "TILEMAP_ADDR", "TILEMAP_LEN",
    "Explorer", "MapMemory", "box_open", "frame_lines", "is_menu",
]
