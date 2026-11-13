"""The Pokemon Yellow spec: PREPARED BUT GATED. pret/pokeyellow has a different WRAM layout, so Yellow gets its
OWN memory family and its own symbol/label tables (not written yet). ``playable=False`` keeps every run path
(``run``, explore, swarm) closed; ``check-rom`` still verifies the hash. See docs/plans/Yellow_Prep.md."""

from pathlib import Path

from pokeagent.game.spec import GameSpec

YELLOW_GATE = ("not playable yet: Yellow's WRAM differs from Red/Blue; it needs its own pokeyellow.sym symbol "
               "table, Pikachu-follow handling and a compat-check pass (docs/plans/Yellow_Prep.md)")

YELLOW = GameSpec(
    key="pokemon-yellow",
    title="Pokemon Yellow",
    rom_sha1=("CC7D03262EBFAF2F06772C1A480C7D9D5F4A38E1",),
    default_rom=Path("roms/Pokemon - Yellow Version - Special Pikachu Edition (USA, Europe) (GBC,SGB Enhanced).gb"),
    screen=(160, 144),
    buttons=("up", "down", "left", "right", "a", "b", "start", "select"),
    memory_family="gen1-yellow",
    owns_legacy_paths=False,
    playable=False,
    gate=YELLOW_GATE,
    ram_table="ram_map_yellow.json",
    symbols="gen1-yellow",
)
