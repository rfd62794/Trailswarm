"""xitems_battle: the in-battle half of the X-item policy. behaviours/battle.py calls ``battle_step`` once per battle step; it decides once
per battle (trainer battles only, readiness margin thin), drives the existing ITEM menu helpers, and logs the use through the ledger."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.behaviours.item_use import close_unwanted_list, item_is_blocked, item_step
from pokeagent.explorer.item_policies import ids, policy, uselog, xitems
from pokeagent.goals import bag_contents


def _decide(ctx, kind: int) -> dict:
    """{'battle', 'item' (0 = none), 'count0', 'reason', 'used', 'before'}; computed once per battle."""
    from pokeagent.explorer.perceive import fighter
    from pokeagent.explorer.training import readiness_for
    from pokeagent.knowledge.damage import PHYSICAL
    from pokeagent.knowledge.kb import table
    from pokeagent.knowledge.party import our_party
    from pokeagent.knowledge.readiness import best_move
    from pokeagent.explorer.item_policies.moves_shield import default_chart
    out = {"battle": ctx.battles, "item": 0, "count0": 0, "reason": "", "used": False, "before": {}}
    if kind != xitems.TRAINER:
        return out
    bag = bag_contents(ctx.emu)
    if not any(bag.get(i, 0) for i in (ids.X_ATTACK, ids.X_SPECIAL)):
        return out
    goals = ctx.goals()
    party = [c for c in our_party(ctx.emu) if c.name != "MAGIKARP"]
    verdict = readiness_for(goals, party)
    boss = policy.next_boss(goals, party)
    physical = None
    if party and boss:
        moves = table(None, "moves")
        name = best_move(party[0], boss[0], default_chart(), moves)[1]
        mv = next((m for m in moves.values() if m["name"] == name), None)
        physical = None if mv is None else mv["type"] in PHYSICAL
    hit = xitems.should_use(kind=kind, bag=bag, score=verdict.score if verdict else None, used_this_battle=0,
                            magikarp_out=fighter(ctx.emu)[0] == 133, physical=physical)
    if hit:
        out.update(item=hit[0], count0=bag.get(hit[0], 0), reason=hit[2], before=uselog.snapshot(ctx.emu, None, hit[0]))
    return out


def battle_step(ctx, lines: list[str], cur_line: str, kind: int) -> Decision | None:
    xs = ctx.xitem
    if xs is None or xs["battle"] != ctx.battles:
        xs = ctx.xitem = _decide(ctx, kind)
    item = xs["item"]
    if not item:
        return None
    if not xs["used"] and bag_contents(ctx.emu).get(item, 0) < xs["count0"]:
        xs["used"] = True
        uselog.record(ctx, item, "x_item", xs["reason"], xs["before"], uselog.snapshot(ctx.emu, None, item), "battle", True)
    if xs["used"] or item_is_blocked(ctx, item):
        return close_unwanted_list(ctx, lines)
    return item_step(ctx, lines, cur_line, item, ids.name_of(item), xs["reason"])
