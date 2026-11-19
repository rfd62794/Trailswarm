"""battle_run: inside a dungeon a wild fight is time lost - run, and keep walking to the exit (unless it is a catch target)."""
from __future__ import annotations

from pokeagent.explorer.catch_list import catch_wanted, dex_owned_count, upcoming_needs
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.world import DUNGEON_MAPS
from pokeagent.goals import bag_contents
from pokeagent.knowledge.catch_math import BALLS
from pokeagent.knowledge.catch_policy import may_throw
from pokeagent.knowledge.flee_catch import FLEE_SPECIES, flee_on_turn
from pokeagent.knowledge.party import our_party, trainer_mon
from pokeagent.ram_symbols import ENEMY_MON, IS_IN_BATTLE
from pokeagent.ramstructs import read_party

POKEDEX_OWNED = 0xD2F7  # wPokedexOwned: bit (dex - 1) of the byte (dex - 1) // 8
POKE_BALL = 0x04
MAX_CAVE_RUNS = 4       # RUN presses per battle before giving up and fighting (a run can fail; 2026-11-06: 2,500 of 4,000 presses were fights)
ENEMY_LVL, ENEMY_MAX = 0xCFF3, 0xCFF4  # wEnemyMonLevel / wEnemyMonMaxHP (2-byte, big-endian); catch.py reads the same addrs


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


def _flee_latch(ctx: ExplorerContext, species: int) -> bool:
    """Compute-and-latch ctx.catch_flee for this (battle, species): would the Catch behaviour engage, and
    is the wild one a flee species (knowledge.flee_catch: it leaves on ITS turn, so the ball must go first)?
    Called lazily the first time a behaviour asks - Readiness and the guards run BEFORE Battle, and Catch
    runs after all of them, so the answer cannot wait for Catch's own step (2026-11-18 real-ROM FAIL: a
    POTION went where the throw belonged because Battle never knew the catch was pending). Mirrors the
    engage gate in behaviours.catch.Catch.step; Catch still does its own catch_want latch and logging."""
    on = False
    name = ((ROM_KB or {}).get("name_of_internal") or {}).get(str(species))
    if (species > 0 and name and ctx.emu.read(IS_IN_BATTLE) == 1
            and may_throw(1, getattr(ctx, "trainer_npc", None), (getattr(ctx, "battle_log", None) or {}).get("kind"))):
        w = None if name in FLEE_SPECIES else trainer_mon(name, ctx.emu.read(ENEMY_LVL))
        if name in FLEE_SPECIES or (w is not None and flee_on_turn(w.name, w.moves)):
            e_max = (ctx.emu.read(ENEMY_MAX) << 8) | ctx.emu.read(ENEMY_MAX + 1)
            bag = bag_contents(ctx.emu)
            balls = sum(bag.get(i, 0) for i in BALLS.values())
            dex_no = int(((ROM_KB or {}).get("dex_of_internal") or {}).get(str(species), 0) or 0)
            if balls and dex_no and e_max and cave_catch_allowed(ctx, species):
                key = (getattr(ctx, "battles", -1), species)
                is_owned = owned(ctx.emu, species)
                want = ctx.catch_want[1] if getattr(ctx, "catch_want", (None, None))[0] == key else catch_wanted(
                    name, our_party(ctx.emu), dex_owned_count(ctx.emu), upcoming_needs(ctx.goals()),
                    owned=is_owned, wants=getattr(ctx, "team_wants", None),
                    build=getattr(getattr(ctx, "opts", None), "build", ""))
                on = bool(want) and (not is_owned or want.startswith(("can learn", "planned", "catch_abra")))
    ctx.catch_flee = ((getattr(ctx, "battles", -1), species), on)
    return on


def flee_throw_pending(ctx: ExplorerContext, species: int | None = None) -> bool:
    """A wanted catch on a flee species owns this wild battle's turns: the ball must go before any potion,
    switch or RUN. While it holds, every behaviour ahead of Catch - Battle's potion / X-item / RUN /
    switch-yield, SwitchOut's swaps, Readiness's busy-A, LoopGuard's box-closing B - must stand down:
    spending OUR turn on any of them hands the wild's turn to Teleport (2026-11-18 real-ROM FAIL: 44 of
    48 Abra encounters never saw a ball). Catch clears the flag when the catch is off for good (a policy
    skip, a party-full with no deposit pick, a bag sequence that gave up)."""
    if species is None:
        species = ctx.emu.read(ENEMY_MON) if ctx.emu.read(IS_IN_BATTLE) else 0
    key = (getattr(ctx, "battles", -1), species)
    cur = getattr(ctx, "catch_flee", (None, False))
    return bool(cur[1]) if cur[0] == key else _flee_latch(ctx, species)


def catch_verdict(ctx: ExplorerContext, ca: dict) -> tuple[bool, str]:
    """(caught, verdict) for a popped catch_attempt at the battle's end. 'SUCCEEDED' needs a ball that
    really left the bag (``thrown``, counted by Catch at the item_use press) AND new ownership: a member
    the party did not have at the attempt's start, or a dex bit set during the fight. The bit alone only
    says 'owned' - a boxed catch read 'SUCCEEDED' on a fight with no throw and a flee (2026-11-18 FAIL)."""
    dn = ca.get("dex") or 0
    joined = ca["species"] in set(m.species for m in read_party(ctx.emu)) - set(ca.get("party0") or ())
    owned_now = bool(dn) and bool(ctx.emu.read(POKEDEX_OWNED + (dn - 1) // 8) >> ((dn - 1) % 8) & 1)
    caught = bool(ca.get("thrown")) and (joined or (owned_now and not ca.get("owned0")))
    return caught, "SUCCEEDED" if caught else ("no throw" if not ca.get("thrown") else "failed")
