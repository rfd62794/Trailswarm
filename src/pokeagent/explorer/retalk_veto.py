"""retalk_veto: turn an A press at an already-memorised, worthless interaction into a harmless B.

Applies ``interaction_policy.decide`` at the one choke point every behaviour passes through (Engine.step). Only the
clear 'no' answers veto: info/sign with their conversation memorised, a giver that already gave, a healer when nobody
needs healing. A hurt party always lets the press through (it may be a healer we have not met yet). Reports the rule
that vetoed, which goes into the decision log."""
from __future__ import annotations

from pokeagent.explorer.interaction_policy import Need, decide, needs_heal
from pokeagent.explorer.interaction_record import stats
from pokeagent.explorer.interaction_types import GIVER, HEALER, INFO, SIGN
from pokeagent.explorer.perceive import DIRS, EFFECT_WINDOW
from pokeagent.explorer.interaction_types import _bag, _party_hp

VETOABLE = (INFO, SIGN, GIVER, HEALER)


def entry_in_front(ctx) -> dict | None:
    """The memorised interaction entry for the tile the player faces: a sign spot, or the NPC standing there."""
    v = ctx.view
    dx, dy = DIRS.get(ctx.facing, (0, 0))
    npc = ctx.mem.npc_at(v.m, v.x + dx, v.y + dy)
    if npc is not None:
        return npc.get("results")
    return ctx.mem.m(v.m).get("interactions", {}).get(f"{v.x},{v.y},{ctx.facing}")


def veto(ctx, decision) -> str | None:
    """None to let the press through, else the policy rule that says talking again is not worth it."""
    if decision.button != "A" or ctx.view.box or ctx.view.battling or ctx.proc is not None:
        return None
    entry = entry_in_front(ctx)
    if not entry or entry.get("type") not in VETOABLE:
        return None
    win = ctx.emu.read_range(*EFFECT_WINDOW)
    party = _party_hp(win)
    if needs_heal(party):
        return None
    talk, rule = decide(entry, Need(party=party, bag_ids=frozenset(_bag(win))))
    if talk:
        return None
    stats(ctx)["retalks_avoided"] = stats(ctx).get("retalks_avoided", 0) + 1
    return f"{rule} (type {entry['type']}, {entry.get('count', 0)} talks so far)"
