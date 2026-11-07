"""Vitamins (HP UP, PROTEIN, IRON, CARBOS, CALCIUM): used at once on the fighter. Shield: never on a Magikarp / with no fighter, and
never past the Gen 1 stat-exp cap (a vitamin adds 2560 and does nothing once the stat is at 25600: 'It won't have any effect')."""
from __future__ import annotations

from pokeagent.explorer.item_policies import ids
from pokeagent.explorer.item_policies.view import MAGIKARP, Mon, fighter_slot_of

STAT_EXP_CAP = 25600
ORDER = (ids.HP_UP, ids.PROTEIN, ids.IRON, ids.CARBOS, ids.CALCIUM)


def capped(mon: Mon, item: int) -> bool:
    return mon.stat_exp[ids.VITAMIN_STAT[item]] >= STAT_EXP_CAP


def should_use(*, bag: dict[int, int], party: list[Mon]) -> tuple[int, int, str] | None:
    slot = fighter_slot_of(party)
    if slot is None or party[slot].species == MAGIKARP:
        return None
    mon = party[slot]
    for item in ORDER:
        if bag.get(item, 0) > 0 and not capped(mon, item):
            return item, slot, f"{ids.name_of(item)} on the fighter {mon.species} (stat exp {mon.stat_exp[ids.VITAMIN_STAT[item]]}/{STAT_EXP_CAP})"
    return None
