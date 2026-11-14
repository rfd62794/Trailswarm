"""Sustain (training controller slice 3): the heal rule's one owner.

Folded in from the deleted ``explorer/grind_heal.py`` and ``explorer/after_heal.py``: the grinding /
needs-heal / potion verdicts, the Pokecenter-exit test and plan_goal's straight-to-the-grass walk, plus
grind_episode's "hurt with no potion" end reason. ``heal_now`` packages them as one frozen record - a
QUERY: no memo, no ctx write (the bandit's decide/clear side effects run only when ``goals`` is passed,
i.e. plan_goal's one call per plan step).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.bandit.hook import heal_push_on
from pokeagent.explorer import train_route
from pokeagent.explorer.economy import heal_items
from pokeagent.explorer.perceive import heal_gate_hp, party_hp, party_needs_heal
from pokeagent.explorer.retreat_risk import PARTY_FLOOR, party_survives
from pokeagent.explorer.world import POKECENTER_MAPS
from pokeagent.goals import bag_contents
from pokeagent.party_view import read_party_view


@dataclass(frozen=True)
class Sustain:
    grinding: bool      # the trainee stage (or a grind episode / the gym hold's grass walk) is live this step
    floor_heal: bool    # needs_heal(ctx, 0.0): the survival-floor verdict while grinding
    weak: bool          # needs_heal(ctx, 0.4): frontier's "leave the grass" verdict
    use_potion: bool    # potion_instead: a field Potion beats the walk
    survives: bool      # party_survives (the planner's _survives)
    push_on: bool       # bandit heal_push_on; False when goals is None

    @property
    def go(self) -> bool:
        return self.floor_heal and not self.use_potion      # a Pokecenter trip is wanted

    def goal_keys(self) -> dict:
        return {"_survives": self.survives, "_push_on": self.push_on}

    why: str            # short text for logs: "grinding+floor", "potion", "ok"


def grinding(ctx) -> bool:
    """The trainee stage (or a grind episode / the gym hold's grass walk) is live this step."""
    return bool(ctx.train_route_live) or bool((ctx.__dict__.get("_grind_state") or {}).get("episode"))


def needs_heal(ctx, fraction: float) -> bool:
    """``party_needs_heal(fraction)`` normally; while grinding, "the next wild fight is not survivable" (or a member fainted)."""
    if not grinding(ctx):
        return party_needs_heal(ctx.emu, fraction)
    # PARTY_FLOOR backstop: party_survives may fall back to a bare 15% fighter test with no KB (review of 84e8023)
    return party_needs_heal(ctx.emu, PARTY_FLOOR) or not party_survives(ctx.emu, ctx.view.m)


def potion_instead(ctx) -> bool:
    """True: a field Potion is cheaper than the walk and nobody has fainted, so skip the Pokecenter trip (CaveTopUp drinks it)."""
    from pokeagent.explorer.behaviours.cave_topup import wants_topup
    return grinding(ctx) and not read_party_view(ctx.emu).any_fainted and wants_topup(ctx)


def heal_now(ctx, goals: dict | None = None) -> Sustain:
    """The heal verdict as one record. With ``goals`` it also asks the bandit (plan_goal's per-step call);
    without it ``push_on`` is False and ``heal_push_on`` is never touched."""
    floor, potion = needs_heal(ctx, 0.0), potion_instead(ctx)
    return Sustain(grinding=grinding(ctx), floor_heal=floor, weak=needs_heal(ctx, 0.4), use_potion=potion,
                   survives=party_survives(ctx.emu, ctx.view.m),
                   push_on=heal_push_on(ctx, goals, *heal_gate_hp(ctx.emu)) if goals is not None else False,
                   why="potion" if potion else "grinding+floor" if floor else "ok")


def leaving(planned, m: int) -> bool:
    """True for the planner's plain walk-out press inside a Pokecenter (not the nurse, PC or a purchase)."""
    return m in POKECENTER_MAPS and planned is not None and "leaving the Pokecenter" in planned[1]


def to_grass(ctx, planned, pos, live: bool):
    """plan_goal's old :131-133 branch: while the trainee stage trains, take the straight walk to the grass when
    the planner has no step or only its 'leaving the Pokecenter' press. Returns planned unchanged when not live."""
    if live and (planned is None or leaving(planned, pos[0])):
        return train_route.step(ctx.mem.data["maps"], pos, ctx.mem.temp_blocked, *heal_gate_hp(ctx.emu),
                                survives=party_survives(ctx.emu, ctx.view.m), heading=getattr(ctx, "facing", None)) or planned
    return planned


def hurt_no_potion(ctx) -> bool:
    """grind_episode's "hurt with no potion" end reason: the next fight is unsurvivable (or a member is
    down) and the bag holds no heal item."""
    hp, mx = party_hp(ctx.emu)
    return bool((mx and not party_survives(ctx.emu, ctx.view.m) or read_party_view(ctx.emu).any_fainted)
                and not heal_items.heal_count(bag_contents(ctx.emu)))
