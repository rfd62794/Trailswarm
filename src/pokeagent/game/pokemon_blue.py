"""The Pokemon Blue spec: same engine and WRAM layout as Red (pret/pokered builds both), so it shares Red's
memory family and symbol table; it owns no legacy paths and its save states are its own."""

from pathlib import Path

from pokeagent.game.spec import LEGACY_FAMILY, GameSpec

BLUE = GameSpec(
    key="pokemon-blue",
    title="Pokemon Blue",
    rom_sha1=("D7037C83E1AE5B39BDE3C30787637BA1D4C48CE2",),
    default_rom=Path("roms/Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb"),
    screen=(160, 144),
    buttons=("up", "down", "left", "right", "a", "b", "start", "select"),
    memory_family=LEGACY_FAMILY,
    owns_legacy_paths=False,
)
