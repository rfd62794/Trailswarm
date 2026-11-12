"""retreat_heal: walk back to a Pokecenter BEFORE the next fight when it would cost too much HP (see explorer.retreat_risk).

It only DECIDES: a retreat is a ``heal_walk.start`` request that StatusCare (the next behaviour) carries out press by
press, so every guard the walk already has (WALK_CAP, cooldown after an abandon, healed check) applies. ``step`` returns
None so the walk's first press comes from StatusCare in the same step. Evaluated every EVERY steps, overworld only.
"""
from __future__ import annotations

from pokeagent.explorer import heal_walk
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.cave_topup import fighter_slot
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.economy import outside_use
from pokeagent.explorer.retreat_risk import assess, party_now
from pokeagent.explorer.status_care import of
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.knowledge import encounters
from pokeagent.ramstructs import read_party

EVERY = 4              # steps between evaluations (HP moves slowly out of battle) (untuned)
LEAD_GATE = 0.80       # the duel rule runs only with the lead below this HP fraction ...
PARTY_GATE = 0.70      # ... or the whole party below this: a trainee at 99% never retreats after a grind fight (untuned)
AFTER_HEAL = 150       # steps after ANY non-abandoned heal_walk end (status_care walks too, intended: they end at a nurse) with no
                       # new precautionary retreat, unless a member has fainted (untuned)
ROUTE_EVERY = 12       # steps a cached walk-to-nurse distance stays good on one map (the BFS is the cost) (untuned)


class RetreatHeal(BehaviourBase):
    name = "retreat_heal"

    def applies(self, ctx: ExplorerContext) -> bool:
        """Pure read: an idle overworld step on the evaluation cadence, nothing else owning the screen."""
        if ctx.view.battling or ctx.in_battle or ctx.view.box or ctx.proc is not None or ctx.center_intent is not None:
            return False
        if ctx.view.m in POKECENTER_MAPS or of(ctx).get("walk") is not None or ctx.step < of(ctx).get("walk_cool", 0):
            return False
        return ctx.step % EVERY == 0

    @staticmethod
    def _hurt(ctx: ExplorerContext, party: list) -> bool:
        """Below the gates, and past the post-heal cooldown unless somebody has fainted. Pure read of the live party."""
        if not party:
            return False
        mx = sum(p.max_hp for p in party) or 1
        lead_mon = party[min(fighter_slot(ctx.emu), len(party) - 1)]   # the fighter, not a Magikarp in training
        lead = lead_mon.hp / (lead_mon.max_hp or 1)
        if lead >= LEAD_GATE and sum(p.hp for p in party) / mx >= PARTY_GATE:
            return False
        recent = ctx.step - of(ctx).get("healed_at", -10 ** 9) < AFTER_HEAL
        return not recent or any(p.hp <= 0 for p in party)

    @staticmethod
    def _walk_frames(ctx: ExplorerContext) -> float | None:
        """Frames to the nearest known Pokecenter, cached per (map, x, y) for ROUTE_EVERY steps."""
        st, key = of(ctx), (ctx.view.m, ctx.view.x, ctx.view.y)
        hit = st.get("retreat_route")
        if hit and hit[0] == key[0] and (hit[1] == key or ctx.step - hit[2] < ROUTE_EVERY):
            return hit[3]
        walk = outside_use.walk_to_center(ctx)
        frames = walk[0] if walk else None
        st["retreat_route"] = (key[0], key, ctx.step, frames)
        return frames

    def step(self, ctx: ExplorerContext) -> Decision | None:
        party_raw = read_party(ctx.emu)
        if not self._hurt(ctx, party_raw):
            return None
        party = party_now(ctx.emu)
        if not party:
            return None
        verdict = assess(party, encounters.species_on(ctx.view.m), self._walk_frames(ctx), None, fighter_slot(ctx.emu))
        if verdict.retreat:
            ctx.log(f"[retreat_heal: {verdict.why}]", "res")
            heal_walk.start(ctx, f"retreat_heal: {verdict.why}", heal_walk.RETREAT_DONE)
        return None
