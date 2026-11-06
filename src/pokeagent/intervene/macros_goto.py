"""goto(map, x, y): walk to a tile over the learned world with the explorer's own Goto behaviour, under the lease.

The rig supplies ``goto_decision(target) -> ("arrived", "") | ("press", button) | ("wait", "") | ("stop", reason)``
(EmuRig drives ``ctx.goto`` and the Goto behaviour). A battle or any box/menu opening mid-walk stops the macro: dialogs
and fights are not something a walk should press through.
"""
from __future__ import annotations

from pokeagent.intervene.macro_core import MacroArgError, Step, press
from pokeagent.intervene.names import map_id
from pokeagent.intervene.screen import ScreenRead

GOTO_CAP = 300


def build_goto(args: dict):
    mid = map_id(args["map"])
    if mid is None:
        raise MacroArgError(f"unknown map {args['map']!r}")
    target = (mid, int(args["x"]), int(args["y"]))

    def step(scr: ScreenRead, st: dict, rig) -> Step:
        if scr.in_battle:
            return Step(stop="interrupted_battle")
        if scr.busy:
            return Step(stop="interrupted_dialog")
        kind, val = rig.goto_decision(target)
        if kind == "arrived":
            return Step(done="arrived")
        if kind == "press":
            return press(val, f"goto {target}")
        return Step(stop=val) if kind == "stop" else Step(wait=8)
    return step, GOTO_CAP
