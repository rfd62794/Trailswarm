"""center_visit: a Pokecenter visit is not a stuck loop.

2026-11-13 A/B: SHAKE lines clustered at Pokecenter map 0x40 (2,6), x23. A heal is the walk in (~7 presses), the nurse dialog
(YES/NO, "OK I'll take your POKeMON", the heal jingle, "We hope to see you again": 20-40 A presses on the SAME tile) and the walk
out, all inside the door column: LoopGuard's "60 presses on <=6 tiles" fired at the exit and its 25-press random walk scattered us
around (2,6), then the walk to the door column restarted. Presses inside a Pokecenter on purpose (a heal walk, the planner's
center intent, or a hurt party) are exempt from THAT window, capped per visit; the 150-press <=2-tile guard and the 40-A guard
still catch a real stall in there.
"""
from __future__ import annotations

from pokeagent.explorer.world import POKECENTER_MAPS

MAX_VISIT_PRESSES = 150   # exempt presses per visit; past it the window shakes as before


def exempt(ctx) -> bool:
    """True while this 60-press window may not shake: inside a Pokecenter, within the per-visit cap."""
    d = ctx.__dict__
    if ctx.view.m not in POKECENTER_MAPS:
        d["center_presses"] = 0   # left: the next visit starts fresh
        return False
    if ctx.step - d.get("center_seen", -10 ** 9) > 5:   # evaluated only while the window holds: a gap = a new visit
        d["center_presses"] = 0
    d["center_seen"] = ctx.step
    n = d["center_presses"] = d.get("center_presses", 0) + 1
    return n <= MAX_VISIT_PRESSES
