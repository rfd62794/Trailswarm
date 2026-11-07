"""Pokecenter checkpoints: on reaching a new town, heal at its Pokecenter so a blackout respawns HERE, not far behind.

Why (2026-11-06): the S.S. Anne segment lost to the bow sailor, blacked out to Cerulean (wLastBlackoutMap 0xD719 = 3, ROM-verified
from checkpoint states: Pallet 0 -> Pewter 2 -> Cerulean 3 after heal_cerulean) and then wandered into the Cerulean Gym for ~800 presses.
Rule: standing in a listed town (or its center) whose id differs from the respawn map -> walk to the center and talk to the nurse.
Capped at CAP planner steps per town per run (the caller counts them) so a missing door or a refused heal cannot loop.
"""
from __future__ import annotations

from pokeagent.explorer.world import WorldGraph
from pokeagent.explorer.ship_gate import ship_stage, weak


def ship_weak(goals: dict) -> bool:
    """Respawn is already Vermilion but the fighter is hurt and the ship is next: heal before boarding anyway."""
    return ship_stage(goals) and weak(goals)

CENTER_OF = {0x05: 0x59}  # town map -> its Pokecenter (Vermilion; add a town once its door is mapped and heal verified)
CAP = 150


def checkpoint_step(g: WorldGraph, goals: dict, pos: tuple, facing: str = "UP") -> tuple[str, str] | None:
    town = next((t for t, c in CENTER_OF.items() if pos[0] in (t, c)), None)
    respawn = goals.get("_respawn")
    if town is None or respawn is None or goals.get("_ckpt_steps", {}).get(town, 0) >= CAP:
        return None
    center = CENTER_OF[town]
    if respawn == town and not (town == 0x05 and ship_weak(goals)):  # healed: the town's center is a stop, not a goal - walk out (no plan reaches here past ss_ticket)
        if pos[0] != center or goals.get("_center_intent"):
            return None
        p = g.path(pos, lambda n: n[0] == town)
        if p:
            return p[0], f"goal checkpoint: leaving the Pokecenter ({len(p)} steps)"
        return (("RIGHT" if pos[1] < 3 else "LEFT"), "goal checkpoint: crossing to the door column") if pos[1] != 3 else ("DOWN", "goal checkpoint: walking out by the door")
    why = f"goal checkpoint: heal at map 0x{center:02X} so a blackout respawns in 0x{town:02X} (not 0x{respawn:02X})"
    if pos[0] == town:
        p = g.path(pos, lambda n: n[0] == center)
        return (p[0], f"{why}, {len(p)} steps") if p else None  # door not learned yet: exploration finds it
    if pos[1] != 3:
        return ("RIGHT" if pos[1] < 3 else "LEFT"), f"{why}: crossing to the counter"
    if pos[2] > 2:
        return "UP", f"{why}: walking up to the nurse"
    return ("A" if facing == "UP" else "UP"), f"{why}: {'talking' if facing == 'UP' else 'facing her'} to the nurse"
