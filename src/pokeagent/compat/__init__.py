"""Game compatibility check: compare two games' map memory and RAM tables; per-game version overlay."""
from pokeagent.compat.addresses import compare_addresses
from pokeagent.compat.maps import compare_memory
from pokeagent.compat.report import build_report

__all__ = ["compare_memory", "compare_addresses", "build_report"]
