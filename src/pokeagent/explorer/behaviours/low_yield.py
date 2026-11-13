"""low_yield: while levelling on purpose, RUN from a wild cocoon instead of fighting it.

2026-11-13 laptop run (12,000 steps, Route 24 grass edge): about 37% of all steps were BATTLE FIGHT, mostly KAKUNA / METAPOD
Harden stalls. A Gen 1 wild cocoon knows only HARDEN: it never hurts us, its defence climbs every turn and a fight is
10-30 turns for one kill of 71-72 base exp. At a step budget that is the worst XP per step on the route, and a RUN costs
one to three presses. The cheapest lever (no new menus: the flee path and its per-battle RUN cap already exist, and the
switch-out lever needs a fighter that finishes fast, which a Harden stall defeats by design).

Only while ``battle_train.grinding`` (a training stage or a grind drill is live), only wild fights, never a species the
Pokedex still wants (battle_run.catch_target), and at most MAX_CAVE_RUNS RUN presses per battle (a failed escape fights on).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours.battle_run import MAX_CAVE_RUNS, catch_target
from pokeagent.explorer.behaviours.battle_train import grinding
from pokeagent.explorer.kb import ROM_KB

STALLERS = frozenset({"KAKUNA", "METAPOD"})  # Harden-only wild moves; the evolved stage of WEEDLE / CATERPIE


def stall_run(ctx, kind: int, species: int, balls: int = 0) -> bool:
    """True: this wild fight is a Harden stall and we are levelling on purpose - flee it."""
    if kind != 1 or species <= 0 or ctx.cave_runs >= MAX_CAVE_RUNS:
        return False
    name = ((ROM_KB or {}).get("name_of_internal") or {}).get(str(species))
    return name in STALLERS and grinding(ctx) and not catch_target(ctx, species, balls)
