"""retalk_veto: turn an A press at an already-memorised, worthless interaction into a harmless B.

Applies ``interaction_policy.decide`` at the one choke point every behaviour passes through (Engine.step). Only the
clear 'no' answers veto: info/sign with their conversation memorised, a giver that already gave, a healer when nobody
needs healing. A hurt party always lets the press through (it may be a healer we have not met yet). Reports the rule
that vetoed, which goes into the decision log."""
from __future__ import annotations

from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.interaction_policy import Need, decide, needs_heal
from pokeagent.explorer.interaction_record import run_id, stats
from pokeagent.explorer.interaction_types import GIVER, HEALER, INFO, SIGN
from pokeagent.explorer.perceive import DIRS, EFFECT_WINDOW
from pokeagent.explorer.world import POKECENTER_MAPS
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


def _thing_in_front(ctx) -> bool:
    v = ctx.view
    dx, dy = DIRS.get(ctx.facing, (0, 0))
    return ctx.mem.npc_at(v.m, v.x + dx, v.y + dy) is not None


def veto(ctx, decision) -> str | None:
    """None to let the press through, else the policy rule that says talking again is not worth it."""
    if decision.behaviour == "goal_talk":
        return None  # a goal that is only met by talking to this person (goal_talk) is a deliberate re-read, whatever the memory says
    if decision.button != "A" or ctx.view.box or ctx.view.battling or ctx.proc is not None:
        return None
    if decision.behaviour == "readiness" and _thing_in_front(ctx):
        # "busy: A in case text is waiting" must never talk to whoever stands in front: that is how the wrong starter ball
        # got taken (a mash A right after a step towards the ball opened the offer and the next A said YES)
        return "readiness mash would talk to the NPC / ball in front: B instead"
    entry = entry_in_front(ctx)
    if not entry or entry.get("type") not in VETOABLE:
        return None
    if ctx.view.m in POKECENTER_MAPS or entry.get("type_votes", {}).get(HEALER):
        return None  # the planner walks into a Pokecenter on purpose (its threshold is 90%, not the veto's 50%); a nurse is never "done"
    win = ctx.emu.read_range(*EFFECT_WINDOW)
    party = _party_hp(win)
    if needs_heal(party):
        return None
    stage = goal_stage(ctx.goals())
    if stage == "first_pokemon" and not party:
        return None  # no starter yet: whatever the spot's memorised type says, the ball in front may be the one still to be taken
    changed = entry.get("goal") not in (None, stage)  # the goal moved on since this spot was last read
    target = ctx.goto and tuple(ctx.goto[:3]) == (ctx.view.m, ctx.view.x, ctx.view.y)
    need = Need(party=party, bag_ids=frozenset(_bag(win)), wants_item=bool(ctx.center_intent), goal_changed=changed, run_id=run_id(ctx),
                reread=bool(target))
    talk, rule = decide(entry, need)
    if talk:
        return None
    stats(ctx)["retalks_avoided"] = stats(ctx).get("retalks_avoided", 0) + 1
    return f"{rule} (type {entry['type']}, {entry.get('count', 0)} talks so far)"
