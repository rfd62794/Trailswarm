"""battle_switch: when the battle behaviour yields this step to SwitchOut.

Battle runs before SwitchOut in the behaviour list, so its potion / RUN answers win by default - and
that is how a losing member gets ground to death while a healthy member waits: a Harden-only KAKUNA
was potioned turn after turn (2026-11-14), and a Rattata facing a wild Paras went 7 HP -> 2 HP ->
fainted on RUN attempts while a healthy Charmeleon sat behind (2026-11-15 review). When switch_choice
would send a fit member in, Battle stands down for the step and SwitchOut drives the swap.
"""
from __future__ import annotations

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.training_ctl import roster
from pokeagent.knowledge.kb import table
from pokeagent.magikarp import switch_candidate
from pokeagent.ramstructs import read_battle_mon


def active_no_damage(ctx: ExplorerContext) -> bool:
    """True when the mon out in this battle cannot hurt anything: every move it knows has power 0 in the ROM
    moves table (a Harden-only KAKUNA). A move id not in the table is unknown, not proven harmless: False."""
    rows = table(None, "moves")
    if not rows:
        return False
    ids = [str(m) for m in read_battle_mon(ctx.emu).moves if m]
    return bool(ids) and all(i in rows and (rows[i].get("power") or 0) <= 0 for i in ids)


def yield_to_switch(ctx: ExplorerContext, kind: int, want_potion: bool) -> bool:
    """True when this step belongs to SwitchOut, not to a potion or a RUN.

    Two cases: the member out cannot hurt the foe at all and a healthy switch-in exists (the cocoon
    rule - in a trainer fight it only vetoes the potion, there is no fleeing anyway), and - wild
    fights only - a matchup pick names a switch-in for the active member (a thin member that CAN hurt
    the foe included: a failed RUN attempt costs the same turn the switch-in spends coming in). Once
    the switch menus gave up this battle the normal rules take over again, and with no candidate
    nothing changes: potion and flee behave exactly as before."""
    if not (want_potion or kind == 1) or getattr(ctx, "switch_gave_up", None) == getattr(ctx, "battles", -1):
        return False
    if active_no_damage(ctx) and switch_candidate(ctx.emu, roster.trainee_slot(ctx)) is not None:
        return True
    if kind != 1:
        return False
    from pokeagent.explorer.behaviours import switch_out as so_mod  # deferred: __init__ imports battle.py first
    return so_mod.matchup_pick(ctx, kind) is not None
