"""The Pokemon Red spec instance."""

from pathlib import Path

from pokeagent.game.spec import GameSpec

RED = GameSpec(
    key="pokemon-red",
    title="Pokemon Red",
    rom_sha1=("EA9BCAE617FDF159B045185467AE58B2E4A48B9A",),
    default_rom=Path("roms/Pokemon Red.gb"),
    screen=(160, 144),
    buttons=("up", "down", "left", "right", "a", "b", "start", "select"),
)
