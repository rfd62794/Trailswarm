"""Target (training controller slice 2): the ONE training point for a session - and it must be real.

Seed 12 (heal_cerulean -> beat_misty, 2026-11-13): 11 of 13 episode starts pinned maps the agent had
never stood on (VIRIDIAN_FOREST 0x33, MT_MOON_B1F 0x3C) - atlas-seeded ledger priors won on xp/min
because ``grind.points.choose`` only applies the no-learned-route skip when ``only_maps`` is given and
a stage with no allow-list leaves it unrestricted. ``known`` adds the missing check: the point's map
has been visited AND a learned route reaches it from here. Target never invents a point: an empty
ledger, or one with nothing known, chooses None.
"""
from __future__ import annotations

from pokeagent.explorer import story_blockers, train_target
from pokeagent.explorer.perceive import lead_level
from pokeagent.grind import points as gp


def known(ctx, point) -> bool:
    """A point the agent can actually train at: the map has been visited AND a learned route reaches it
    from here. Reads ``mem.data["maps"]`` directly - ``mem.m`` would setdefault the entry and mark the
    map known."""
    maps = ctx.mem.data.get("maps", {})
    if not (maps.get(str(point.map_id)) or {}).get("visited"):
        return False                                   # never stood on that map: a phantom pin
    here = (ctx.view.m, ctx.view.x, ctx.view.y)
    return gp.travel_steps(maps, here, point.map_id) < gp.FAR_TRAVEL   # no learned path -> reject


def choose(ctx, ledger, levels, need, slot=None):
    """The ONE training point for a session, or None (empty ledger / nothing known fits): the existing
    scorer ``gp.choose`` over only the points that pass ``known``. Never invents a point."""
    pts = {m: p for m, p in ledger.points.items() if known(ctx, p)}
    if not pts:
        return None
    return gp.choose(gp.GrindLedger(pts), levels, need, (ctx.view.m, ctx.view.x, ctx.view.y), ctx.mem,
                     trainee_slot=slot, blocked=story_blockers.blocked_tiles(ctx),
                     only_maps=train_target.only_maps(ctx))


def wants_training(ctx) -> bool:
    """GrindDrill.applies' read: an episode is live, or the trainee is under the train need. Exit
    (slice 5) will absorb the under-level half; until then it lives here, behaviour identical."""
    ep = ctx.__dict__.get("_grind_state", {}).get("episode")     # the live episode, read off ctx - never imported
    return ep is not None or 0 < (getattr(ctx, "gate_lvl", None) or lead_level(ctx.emu)) < getattr(ctx, "train_need", 0)
