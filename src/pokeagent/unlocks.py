"""What the party can DO now, read from RAM (the unlock-layer spec's section 1: Cut only in this step).

These are the capability tags the campaign goals' ``needs`` names (``needs: ["cut"]`` walls off the Vermilion gym
and everything behind it until the tag turns up here). Later steps add surf/strength/flash/bike/poke_flute the
same way; ``campaign.agent_capabilities`` unions this set with the env override and the curriculum's evidence.
"""
from __future__ import annotations

from pokeagent.campaign import party_knows_move

CUT = 15  # pokered move id of CUT (HM01)


def capabilities(emu) -> frozenset[str]:
    """{"cut"} when any party member knows CUT; never raises (a failing RAM read answers the empty set)."""
    try:
        return frozenset({"cut"}) if party_knows_move(emu, CUT) else frozenset()
    except Exception:
        return frozenset()
