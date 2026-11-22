"""Game key -> ram_map path. The map is per memory family, not per game: Red and Blue share
gen1-pokemon memory, and the legacy family keeps today's ``ram_map.json`` name so nothing else
moves. Nothing here names Red, an address or a pokered label."""
from __future__ import annotations

from pathlib import Path

from pokeagent.game.registry import get_game
from pokeagent.game.spec import LEGACY_FAMILY
from pokeagent.ramlab.labels import DATA


def map_path_for(game_key: str) -> Path:
    """data/ram_map.json for the legacy family, else data/ram_map.<memory_family>.json.
    get_game raises a KeyError naming the known games (let it out); a missing family map raises
    ValueError naming the file to build."""
    spec = get_game(game_key)
    name = "ram_map.json" if spec.memory_family == LEGACY_FAMILY else f"ram_map.{spec.memory_family}.json"
    path = DATA / name
    if not path.is_file():
        raise ValueError(f"{path} does not exist: build it with tools/build_ram_map.py "
                         f"from {game_key}'s sym file")
    return path
