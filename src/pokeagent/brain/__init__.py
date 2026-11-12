"""Brain tools: pure queries over the map memory (runs/maps.json) for Claude, the CLI and MCP.

Everything here is a pure function of the loaded maps.json ``data`` dict (plus an optional
journal edit list) - no UI, no emulator, no file writes. The CLI (``pokeagent brain`` /
``tools/brain.py``) and the MCP ``brain_*`` tools are thin wrappers over these.
"""
from __future__ import annotations

from pokeagent.brain.audit import audit
from pokeagent.brain.cleanplan import plan_clean
from pokeagent.brain.diff import diff
from pokeagent.brain.find import find
from pokeagent.brain.lessons import lessons
from pokeagent.brain.maps import map_view, maps_summary, overlay_cells
from pokeagent.brain.qtools import q_state, q_summary
from pokeagent.brain.tile import tile_facts

__all__ = [
    "audit", "diff", "find", "lessons", "map_view", "maps_summary", "overlay_cells",
    "plan_clean", "q_state", "q_summary", "tile_facts",
]
