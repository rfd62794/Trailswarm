"""X items: in boss / trainer battles only, when the readiness margin is thin, one per battle. The decision is this pure function;
the battle hook (xitems_battle) is a few lines in behaviours/battle.py. Shield: never in a wild fight, never twice in one battle,
never while the Magikarp (SPLASH) is the one in the ring."""
from __future__ import annotations

from pokeagent.explorer.item_policies import ids

THIN_LOW, THIN_HIGH = -0.15, 0.45     # readiness score band that counts as thin (the 'ready' bar is MARGIN = 0.30)
TRAINER = 2                           # wIsInBattle 2 = trainer


def should_use(*, kind: int, bag: dict[int, int], score: float | None, used_this_battle: int, magikarp_out: bool,
               physical: bool | None) -> tuple[int, None, str] | None:
    """kind = wIsInBattle (1 wild, 2 trainer). ``physical``: the fighter's best move is physical (X ATTACK) or special (X SPECIAL);
    None = unknown, no X item."""
    if kind != TRAINER or score is None or used_this_battle >= 1 or magikarp_out or physical is None:
        return None
    if not THIN_LOW <= score < THIN_HIGH:
        return None
    item = ids.X_ATTACK if physical else ids.X_SPECIAL
    if bag.get(item, 0) <= 0:
        return None
    return item, None, f"trainer battle with a thin margin (score {score:+.2f}): {ids.name_of(item)}"
