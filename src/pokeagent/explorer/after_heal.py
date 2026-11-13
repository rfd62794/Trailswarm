"""after_heal: leave the Pokecenter by the way that goes straight to the grass (2026-11-13 A/B: 15.6% of steps were "walking to
grass", 1.9% "leaving the Pokecenter").

While the trainee stage trains, the planner's own "leaving the Pokecenter" press only reaches the doorstep; from there another
planner/frontier round chose the way to the grass. train_route.step already BFS-walks the learned graph from inside the center
to the target grass (through the door warp), so the exit is that walk: the same press, one decision, no stop on the doorstep.
"""
from __future__ import annotations

from pokeagent.explorer.world import POKECENTER_MAPS


def leaving(planned, m: int) -> bool:
    """True for the planner's plain walk-out press inside a Pokecenter (not the nurse, PC or a purchase)."""
    return m in POKECENTER_MAPS and planned is not None and "leaving the Pokecenter" in planned[1]
