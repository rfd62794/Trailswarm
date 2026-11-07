"""outside_use: drink a Potion instead of walking to a Pokecenter when the walk costs more than the Potion is worth.

Walk cost (frames, there and back): the plain walking frames plus the risk of a wild fight at low HP on the grass tiles
(ENCOUNTER_RATE x BATTLE_FRAMES per grass tile, multiplied up the lower the HP), priced at YEN_PER_FRAME. The Potion wins when
that exceeds its price. A Potion NEVER replaces the heal on reaching a town whose Pokecenter we have not stood in yet: the nurse
visit is what moves the blackout respawn point forward, and the other builder's checkpoints depend on it.
"""
from __future__ import annotations

from pokeagent.explorer.economy import heal_items, ledger
from pokeagent.explorer.economy.prices import HEAL_HP, POTION, price
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.world import POKECENTER_MAPS, WorldGraph
from pokeagent.goals import bag_contents
from pokeagent.legs import grid as G
from pokeagent.legs.par import map_par

YEN_PER_FRAME = 0.1       # what a frame of walking is worth: 3000 frames (a minute) = one Potion
ROUND_TRIP = 2            # the walk to the nurse is paid again on the way back
FIELD_BELOW = 0.5         # HP fraction under which a field Potion is considered
MIN_MISSING = 15          # HP missing below which a 20 HP Potion would be wasted
DANGER_MULT = 3.0         # extra encounter cost at zero HP (x1 at full HP)
GRASS_GUESS = 0.3         # grass share of a route whose tiles are only known as a learned-step count
RECHECK_EVERY = 25        # steps between walk-cost evaluations
_grids = False            # lazy G.rom_grids(): False = not tried, None = no ROM


def walk_frames(frames: float, grass_tiles: int, hp: int, mx: int) -> float:
    """Round-trip cost in frames: plain walking plus the low-HP encounter risk. ``frames`` may include the grass penalty (par)."""
    plain = frames - grass_tiles * G.GRASS_PENALTY
    risk = grass_tiles * G.ENCOUNTER_RATE * G.BATTLE_FRAMES * (1 + DANGER_MULT * (1 - hp / mx))
    return ROUND_TRIP * (max(0.0, plain) + risk)


def potion_beats_walk(frames: float, grass_tiles: int, hp: int, mx: int, potion_price: int | None = None,
                      yen_per_frame: float = YEN_PER_FRAME) -> bool:
    """Pure rule: the Potion is the cheaper way to get HP back than the Pokecenter walk."""
    if mx <= 0 or hp <= 0 or hp >= mx * FIELD_BELOW or mx - hp < MIN_MISSING:
        return False
    cost = walk_frames(frames, grass_tiles, hp, mx) * yen_per_frame
    return cost > (price(POTION) if potion_price is None else potion_price)


def _get_grids():
    global _grids
    if _grids is False:
        _grids = G.rom_grids()
    return _grids


def walk_to_center(ctx, get=None):
    """``(frames, grass_tiles, center_map)`` to the nearest known Pokecenter, or None. Same-map door: par on the ROM grid;
    otherwise the learned-world path (16 frames a step, GRASS_GUESS of it grass)."""
    m, x, y = ctx.pos()
    maps = ctx.mem.data.get("maps", {})
    get = get if get is not None else _get_grids()
    doors = [(tuple(int(v) for v in k.split(",")[:2]), w[0]) for k, w in maps.get(str(m), {}).get("warps", {}).items() if w[0] in POKECENTER_MAPS]
    best = None
    for door, center in doors:
        res = map_par(get, m, (x, y), door)
        if res and (best is None or res[0] < best[0]):
            grid = get(m)
            best = (res[0], sum(bool(grid.grass[cy, cx]) for cx, cy in res[1]), center)
    if best:
        return best
    g = WorldGraph(maps)
    g.blocked_now = frozenset(ctx.mem.temp_blocked)
    found = g._bfs_node((m, x, y), lambda n: n[0] in POKECENTER_MAPS, 5000)  # not .path(): that sets par_follow's last_route
    if not found or not found[1]:
        return None
    node, path = found
    return G.FRAME_WALK * len(path), int(len(path) * GRASS_GUESS), node[0]


def field_wants(ctx, get=None) -> bool:
    """Should the cave top-up sequence drink a Potion here (outside a dungeon, no fight)? Cached for RECHECK_EVERY steps."""
    hp, mx = party_hp(ctx.emu)
    if not mx or ctx.view.m in POKECENTER_MAPS or heal_items.heal_count(bag_contents(ctx.emu)) <= 0 or ctx.center_intent:
        return False
    if not (0 < hp < mx * FIELD_BELOW):
        return False
    led = ledger.of(ctx)
    if ctx.step < led.field_check_at:
        return led.field_decision
    led.field_check_at = ctx.step + RECHECK_EVERY
    led.field_decision = False
    walk = walk_to_center(ctx, get)
    if walk is None or walk[2] is None or walk[2] not in led.visited_centers:
        return False   # unknown route, or a Pokecenter we have not been in: walk and heal there (respawn point)
    item = heal_items.pick_for_missing(bag_contents(ctx.emu), mx - hp)
    led.field_decision = potion_beats_walk(walk[0], walk[1], hp, mx, price(item))
    if led.field_decision:
        ctx.log(f"[field potion: walk to the Pokecenter is {walk[0]:.0f} frames ({walk[1]} grass tiles), HP {hp}/{mx}: drinking a heal item instead]", "res")
    return led.field_decision


__all__ = ["field_wants", "potion_beats_walk", "walk_frames", "walk_to_center", "HEAL_HP"]
