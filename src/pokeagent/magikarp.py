"""The Magikarp plan: buy it at the Mt Moon Pokemon Center, keep it first in the party, switch it out on turn one.

Pure RAM readers and thresholds (no behaviour state). Internal species ids are ROM-verified (kb name_of_internal):
133 = MAGIKARP, 22 = GYARADOS. Gen 1 splits a battle's experience among every Pokemon that took part, so a Magikarp
that leads and is swapped out at once still earns a share. It evolves at level 20.
"""
from __future__ import annotations

from pokeagent.ramstructs import PARTY_COUNT, read_battle_mon, read_party
from pokeagent.ramworld import read_money

MAGIKARP, GYARADOS = 133, 22
MAGIKARP_PRICE = 500                 # the salesman's price in the Mt Moon Pokemon Center (map 0x44)
MT_MOON_CENTER = 0x44
SWITCH_MIN_HP = 0.25                 # never send in a member below this HP fraction (directive section 2.3)
EVOLVE_LEVEL = 20
IN_BATTLE = 0xD057


def party_species(emu) -> list[int]:
    n = min(emu.read(PARTY_COUNT), 6)
    return list(emu.read_range(0xD164, n)) if n else []


def trainee_slot(emu) -> int | None:
    """Party index of the Magikarp being switch-trained, else None (Gyarados is a normal team member)."""
    sp = party_species(emu)
    return sp.index(MAGIKARP) if MAGIKARP in sp else None


def can_buy(emu) -> bool:
    """Money for it and a free party slot (the directive's gate)."""
    return read_money(emu) >= MAGIKARP_PRICE and emu.read(PARTY_COUNT) < 6


def magikarp_goal_settled(emu, st: dict, seen: set) -> bool:
    """buy_magikarp: owned (or already evolved), or no longer a live option (Mt Moon 1F entered, cannot afford/no room)."""
    sp = party_species(emu)
    if MAGIKARP in sp or GYARADOS in sp:
        st["had_magikarp"] = True
    return bool(st.get("had_magikarp")) or 0x3B in seen or not can_buy(emu)


def gyarados_goal(emu, st: dict) -> bool:
    """Side goal: a GYARADOS in the party (sticky)."""
    if GYARADOS in party_species(emu):
        st["had_gyarados"] = True
    return bool(st.get("had_gyarados"))


def switch_candidate(emu) -> int | None:
    """Party index of the strongest healthy non-trainee (HP >= SWITCH_MIN_HP of max), else None."""
    best = None
    for i, p in enumerate(read_party(emu)):
        if p.species == MAGIKARP or p.max_hp == 0 or p.hp <= 0 or p.hp / p.max_hp < SWITCH_MIN_HP:
            continue
        if best is None or (p.level, p.hp) > (best[1], best[2]):
            best = (i, p.level, p.hp)
    return best[0] if best else None


def fighter(emu) -> tuple[int, int, int, int]:
    """(species, level, hp, max_hp) of whoever is doing the fighting: the party lead normally; while a Magikarp is
    in the party, the battle's active mon in a fight, or else the strongest non-Magikarp member."""
    party = read_party(emu)
    if not party:
        return 0, 0, 0, 0
    if not any(p.species == MAGIKARP for p in party):
        p = party[0]
        return p.species, p.level, p.hp, p.max_hp
    if emu.read(IN_BATTLE):
        b = read_battle_mon(emu)
        if b.species:
            return b.species, b.level, b.hp, b.max_hp
    others = [p for p in party if p.species != MAGIKARP] or party
    p = max(others, key=lambda q: (q.hp > 0, q.level, q.hp))
    return p.species, p.level, p.hp, p.max_hp


def magikarp_stats(emu) -> dict | None:
    """{level, exp, slot} of the trainee for the status line, else None."""
    for i, p in enumerate(read_party(emu)):
        if p.species == MAGIKARP:
            return {"level": p.level, "exp": p.exp, "slot": i}
    return None
