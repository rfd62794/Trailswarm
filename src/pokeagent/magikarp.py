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
BUY_STEP_CAP = 600                   # steps in/around the center without buying before the goal is dropped for the run
GYARADOS_IDLE_CAP = 300                  # consecutive plan steps at the gyarados stage with the training gate closed/lifted before the goal is settled
GYARADOS_STEP_CAP = 6000             # steps on the stage without evolving before the goal is settled for this run (named; tune from runs)
MAX_RUNS = 5                         # RUN attempts per battle when nobody healthy can replace the trainee
IN_BATTLE = 0xD057


def party_species(emu) -> list[int]:
    n = min(emu.read(PARTY_COUNT), 6)
    return list(emu.read_range(0xD164, n)) if n else []


def trainee_slot(emu) -> int | None:
    """Party index of the Magikarp being switch-trained, else None (Gyarados is a normal team member)."""
    sp = party_species(emu)
    return sp.index(MAGIKARP) if MAGIKARP in sp else None


def trainee_slot_for(emu, named: int | None, breakers=(), wild=None) -> int | None:
    """The switch-training slot: the Magikarp's when one is in the party; else the exp-spread rotation's
    pick (knowledge.team_plan.trainee_slot): `named` (the slot ctx.train_member names) when it is a
    non-lead member at least TEAM_GAP below the lead's level, else the lowest band breaker of `breakers`
    that can survive `wild` (a grind leads the breaker and swaps it out on turn one for the shared exp)."""
    t = trainee_slot(emu)
    if t is not None:
        return t
    from pokeagent.knowledge import team_plan  # deferred: readiness imports this module for EVOLVE_LEVEL
    return team_plan.trainee_slot(read_party(emu), named, breakers, wild)


def can_buy(emu) -> bool:
    """Money for it and a free party slot (the directive's gate)."""
    return read_money(emu) >= MAGIKARP_PRICE and emu.read(PARTY_COUNT) < 6


def magikarp_goal_settled(emu, st: dict, seen: set) -> bool:
    """buy_magikarp: owned (or already evolved), or no longer a live option. "No longer an option" is only judged where
    the salesman is: standing in the Mt Moon Pokemon Center (cannot afford it / no room: latched as st["buy_skipped"]),
    or later in the story (Mt Moon 1F entered), or the step cap spent (st["buy_skipped"]). Money spent elsewhere
    (e.g. on items in Pewter, before Brock) must not settle it: the plan is still pending until Route 4."""
    sp = party_species(emu)
    if MAGIKARP in sp or GYARADOS in sp:
        st["had_magikarp"] = True
    if not st.get("had_magikarp") and not can_buy(emu) and emu.read(0xD35E) == MT_MOON_CENTER:
        st["buy_skipped"] = True  # sticky: leaving the center must not reopen the goal
    return bool(st.get("had_magikarp")) or bool(st.get("buy_skipped")) or 0x3B in seen


def gyarados_goal(emu, st: dict) -> bool:
    """A GYARADOS in the party (sticky)."""
    if GYARADOS in party_species(emu):
        st["had_gyarados"] = True
    return bool(st.get("had_gyarados"))


def gyarados_goal_settled(emu, st: dict, seen: set) -> bool:
    """Ladder goal: a GYARADOS in the party (sticky), OR no Magikarp was ever owned, OR the stage ran out of steps
    (st["gyarados_skipped"]). It must NEVER block the route."""
    return (gyarados_goal(emu, st)
            or (not st.get("had_magikarp") and MAGIKARP not in party_species(emu))
            or bool(st.get("gyarados_skipped")))


def team_ready_settled(emu, st: dict, seen: set) -> bool:
    """team_ready (the ladder goal that replaced gyarados, same slot): True once the hurt-lead sim says the party
    beats the next boss (plan_goal sets ``team_ready_ok`` each step from team_for().ready and latches
    ``had_team_ready``), when the stage's step cap is spent (``team_ready_skipped``), or when there is no boss/ROM
    data to judge by (``team_ready_nodata``). It must NEVER block the route."""
    if st.get("team_ready_ok") or st.get("team_ready_skipped") or st.get("team_ready_nodata"):
        st["had_team_ready"] = True  # settled is sticky: a later not-ready step must not reopen the route
    return bool(st.get("had_team_ready"))


def switch_candidate(emu, trainee: int | None = None) -> int | None:
    """Party index of the strongest healthy non-trainee (HP >= SWITCH_MIN_HP of max), else None.
    `trainee` = the slot being switch-trained (trainee_slot_for); without one every MAGIKARP stays out, as before."""
    best = None
    for i, p in enumerate(read_party(emu)):
        is_trainee = i == trainee if trainee is not None else p.species == MAGIKARP
        if is_trainee or p.max_hp == 0 or p.hp <= 0 or p.hp / p.max_hp < SWITCH_MIN_HP:
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
