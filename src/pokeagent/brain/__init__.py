"""Brain tools: pure queries over the map memory (runs/maps.json) for Claude, the CLI and MCP.

Everything here is a pure function of the loaded maps.json ``data`` dict (plus an optional
journal edit list) - no UI, no emulator, no file writes. The CLI (``pokeagent brain`` /
``tools/brain.py``) and the MCP ``brain_*`` tools are thin wrappers over these.
"""
from __future__ import annotations

from pokeagent.brain.assists import assists_report
from pokeagent.brain.compare import compare_memory
from pokeagent.brain.diff import diff
from pokeagent.brain.find import find
from pokeagent.brain.ledges import classify_wall, opposite, parse_edge
from pokeagent.brain.lessons import lessons
from pokeagent.brain.maps import map_view, maps_summary, overlay_cells
from pokeagent.brain.qtools import q_state, q_summary
from pokeagent.brain.seed import seed_memory
from pokeagent.brain.tile import tile_facts

__all__ = [
    "assists_report", "classify_wall", "compare_memory", "diff", "find", "lessons",
    "map_view", "maps_summary", "opposite", "overlay_cells", "parse_edge",
    "q_state", "q_summary", "seed_memory", "tile_facts",
]
