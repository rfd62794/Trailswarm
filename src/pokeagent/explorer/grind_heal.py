"""grind_heal: while the trainee stage grinds, heal on the SURVIVAL FLOOR and drink a Potion for a long walk.

2026-11-13 A/B: 8.7% of steps were the walk to the Pokecenter plus 1,290 steps inside map 0x40. The grind used fixed HP fractions:
retreat_heal's LEAD_GATE 0.80 / PARTY_GATE 0.70 pre-gates and frontier's ``party_needs_heal(0.4)`` ("weak": steer OFF the grass).
Both ignore what the next fight costs; retreat_risk.party_survives (SURVIVE_NEAR / SURVIVE_FAR margins after the worst wild duel)
already answers that and the grind gates (train_route, grind_episode) use it. So while grinding:
  * the heal trip starts only when the party does NOT survive the next wild fight (or a member fainted);
  * frontier is "weak" (leaves the grass) on the same test;
  * a Potion in the bag that beats the walk (economy.outside_use.field_wants, drunk by CaveTopUp, the path after_victory_rules'
    "potion" action already feeds) replaces the trip.
Outside a grind nothing changes.
"""
from __future__ import annotations

from pokeagent.explorer.perceive import party_needs_heal
from pokeagent.explorer.retreat_risk import party_survives
from pokeagent.party_view import read_party_view


def grinding(ctx) -> bool:
    """The trainee stage (or a grind episode / the gym hold's grass walk) is live this step."""
    return bool(ctx.train_route_live) or bool((ctx.__dict__.get("_grind_state") or {}).get("episode"))


def needs_heal(ctx, fraction: float) -> bool:
    """``party_needs_heal(fraction)`` normally; while grinding, "the next wild fight is not survivable" (or a member fainted)."""
    if not grinding(ctx):
        return party_needs_heal(ctx.emu, fraction)
    return read_party_view(ctx.emu).any_fainted or not party_survives(ctx.emu, ctx.view.m)


def potion_instead(ctx) -> bool:
    """True: a field Potion is cheaper than the walk and nobody has fainted, so skip the Pokecenter trip (CaveTopUp drinks it)."""
    from pokeagent.explorer.behaviours.cave_topup import wants_topup
    return grinding(ctx) and not read_party_view(ctx.emu).any_fainted and wants_topup(ctx)
