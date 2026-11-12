"""retreat_heal: walk back to a Pokecenter BEFORE the next fight when it would cost too much HP (see explorer.retreat_risk).

It only DECIDES: a retreat is a ``heal_walk.start`` request that StatusCare (the next behaviour) carries out press by
press, so every guard the walk already has (WALK_CAP, cooldown after an abandon, healed check) applies. ``step`` returns
None so the walk's first press comes from StatusCare in the same step. Evaluated every EVERY steps, overworld only.
"""
from __future__ import annotations

from pokeagent.explorer import heal_walk
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.retreat_risk import assess, party_now
from pokeagent.explorer.status_care import of
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.knowledge import encounters
from pokeagent.ramstructs import read_party

EVERY = 4   # steps between evaluations (the route search is the cost; HP moves slowly out of battle) (untuned)


class RetreatHeal(BehaviourBase):
    name = "retreat_heal"

    def applies(self, ctx: ExplorerContext) -> bool:
        """Pure read: an idle overworld step on the evaluation cadence, nothing else owning the screen."""
        if ctx.view.battling or ctx.in_battle or ctx.view.box or ctx.proc is not None or ctx.center_intent is not None:
            return False
        if ctx.view.m in POKECENTER_MAPS or of(ctx).get("walk") is not None or ctx.step < of(ctx).get("walk_cool", 0):
            return False
        return ctx.step % EVERY == 0

    def step(self, ctx: ExplorerContext) -> Decision | None:
        if all(p.hp >= p.max_hp for p in read_party(ctx.emu)):
            return None        # a full party never retreats: skip the route search
        party = party_now(ctx.emu)
        if not party:
            return None
        walk = outside_use.walk_to_center(ctx)
        verdict = assess(party, encounters.species_on(ctx.view.m), walk[0] if walk else None)
        if verdict.retreat:
            ctx.log(f"[retreat_heal: {verdict.why}]", "res")
            heal_walk.start(ctx, f"retreat_heal: {verdict.why}")
        return None
