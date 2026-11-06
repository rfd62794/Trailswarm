"""battle_run: inside a dungeon a wild fight is time lost - run, and keep walking to the exit (unless it is a catch target)."""
from __future__ import annotations

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.world import DUNGEON_MAPS

POKEDEX_OWNED = 0xD2F7  # wPokedexOwned: bit (dex - 1) of the byte (dex - 1) // 8
POKE_BALL = 0x04
MAX_CAVE_RUNS = 4       # RUN presses per battle before giving up and fighting (a run can fail; 2026-11-06: 2,500 of 4,000 presses were fights)


def owned(emu, species: int) -> bool:
    """Is this internal species id already in the Pokedex as owned? False when unknown (so we do not skip a new one)."""
    dex = int(((ROM_KB or {}).get("dex_of_internal") or {}).get(str(species), 0) or 0)
    return dex > 0 and bool(emu.read(POKEDEX_OWNED + (dex - 1) // 8) >> ((dex - 1) % 8) & 1)


MAX_CAVE_BALLS = 2        # balls thrown at ONE new species per run inside a dungeon; after that (or if it fails) we run from it
CATCH_MIN_HP = 0.5        # fighter HP fraction needed to START a catch sequence in a dungeon


def cave_catch_allowed(ctx: ExplorerContext, species: int) -> bool:
    """Inside a dungeon a new species earns ONE sequence per run (max MAX_CAVE_BALLS), started only with a healthy fighter;
    elsewhere the old catch rules apply unchanged."""
    if ctx.view.m not in DUNGEON_MAPS:
        return True
    tried = ctx.cave_catch_balls.get(species, 0)
    if tried >= MAX_CAVE_BALLS:
        return False
    if tried == 0:
        hp, mx = party_hp(ctx.emu)
        return mx > 0 and hp / mx >= CATCH_MIN_HP
    return True  # a started sequence finishes its (at most MAX_CAVE_BALLS) throws


def catch_target(ctx: ExplorerContext, species: int, balls: int) -> bool:
    """The catch rule's own test: a ball in the bag, a species the Pokedex does not own yet, and (in a dungeon) budget left."""
    dex = int(((ROM_KB or {}).get("dex_of_internal") or {}).get(str(species), 0) or 0)
    return bool(balls) and dex > 0 and not owned(ctx.emu, species) and cave_catch_allowed(ctx, species)


def cave_run(ctx: ExplorerContext, kind: int, species: int, balls: int = 0) -> bool:
    """Wild fight (kind 1) inside DUNGEON_MAPS, not a catch target, and fewer than MAX_CAVE_RUNS run attempts this battle."""
    return (kind == 1 and ctx.view.m in DUNGEON_MAPS and species > 0 and ctx.cave_runs < MAX_CAVE_RUNS
            and not catch_target(ctx, species, balls))
