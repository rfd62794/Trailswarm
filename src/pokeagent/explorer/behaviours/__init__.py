"""The explorer's behaviours, in the demo's priority order (the old ``agent_step`` top to bottom)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.advance_dialog import AdvanceDialog, NamingKeyboard
from pokeagent.explorer.behaviours.base import Behaviour, BehaviourBase, Decision, no_press
from pokeagent.explorer.behaviours.battle import Battle
from pokeagent.explorer.behaviours.battle_moves import BattleMoves
from pokeagent.explorer.behaviours.catch import Catch
from pokeagent.explorer.behaviours.frontier import ExploreBurst, Frontier
from pokeagent.explorer.behaviours.goto import Goto
from pokeagent.explorer.behaviours.guards import LoopGuard, StallGuard
from pokeagent.explorer.behaviours.heal import Heal
from pokeagent.explorer.behaviours.menu import Menu
from pokeagent.explorer.behaviours.pickup import Pickup
from pokeagent.explorer.behaviours.plan_goal import PlanGoal
from pokeagent.explorer.behaviours.procedures import Procedures
from pokeagent.explorer.behaviours.readiness import Readiness, SettleWait
from pokeagent.explorer.behaviours.replay_beat import BeatStart, ReplayBeat, ReplayInterrupt

__all__ = [
    "AdvanceDialog", "Battle", "BattleMoves", "BeatStart", "Behaviour", "BehaviourBase", "Catch", "Decision",
    "ExploreBurst", "Frontier", "Goto", "Heal", "LoopGuard", "Menu", "NamingKeyboard", "Pickup", "PlanGoal",
    "Procedures", "Readiness", "ReplayBeat", "ReplayInterrupt", "SettleWait", "StallGuard",
    "default_behaviours", "no_press",
]


def default_behaviours() -> list[Behaviour]:
    """Ask in this order; the first one that applies and returns a Decision wins (None = pass to the next).

    Same order as the old agent_step: settle pause, loop guards, input readiness, replay interrupt, battle
    (potion/flee, catch, moves), text boxes (keyboard, beat replay, dialog, menu), procedures, goto, replays,
    the stall guard, the Mom-heal guard, new-map exploration, the goal planner, nearby item-ball pickups,
    and finally plain exploration.
    """
    return [
        SettleWait(), LoopGuard(), Readiness(), ReplayInterrupt(),
        Battle(), Catch(), BattleMoves(),
        NamingKeyboard(), BeatStart(), AdvanceDialog(), Menu(),
        Procedures(), Goto(), ReplayBeat(), StallGuard(), Heal(),
        ExploreBurst(), Pickup(), PlanGoal(), Frontier(),
    ]
