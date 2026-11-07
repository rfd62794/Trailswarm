"""battle_train: while the agent is deliberately levelling, a wild fight is the point - do not flee it for being mildly hurt.

2026-11-07 (grind drill, Route 1, L7 Bulbasaur): 11 of 13 wild battles were fled at 8/23 HP (35%, under the 0.4 ``weak`` line),
so the drill measured 17.6 XP/min against an atlas prior of 80.4. Fleeing never heals, so the agent kept fleeing at the same HP.
"""
from __future__ import annotations

from pokeagent.bandit.hook import FIGHT_FLOOR
from pokeagent.explorer.par_follow import training

OVER_LEVEL = 3   # an enemy this many levels above the lead is a real threat, not XP: flee
HIT_CAP_PER_LEVEL = 2  # one hit from a wild mon of level L is estimated at most max(4, 2 * L): the damage ledger holds outliers (46-51 HP for a Pidgey)


def grinding(ctx) -> bool:
    """Levelling on purpose: the lead is under the training target, or a grind drill is running."""
    return getattr(ctx.opts, "drill_grind", None) is not None or training(ctx)


def train_fight(ctx, hp: int, mx: int, my_lvl: int, e_lvl: int, expected: int) -> bool:
    """True: fight this wild battle even though the usual rules (weak / hurry / cave run) say flee.

    Still flee when the lead is under the bandit's FIGHT_FLOOR of HP or cannot take one of the enemy's worst
    hits (observed, capped by its level), or when the enemy is badly over-level. A fight that goes badly flips ``weak``
    back on at the next decision (HP under the floor), and the flee runs as before."""
    if not grinding(ctx) or mx <= 0:
        return False
    if e_lvl > my_lvl + OVER_LEVEL:
        return False
    hit = min(expected, max(4, HIT_CAP_PER_LEVEL * e_lvl))
    return hp / mx >= FIGHT_FLOOR and hp > hit
