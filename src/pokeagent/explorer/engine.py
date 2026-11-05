"""Engine: one explorer step = the selector chooses, the presser presses, the decision log records.

This is the old ``agent_step()`` closure's job, minus the window and the HTTP API (those stay in the demo).
"""
from __future__ import annotations

from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.decisions import DecisionLog, classify_outcome, goal_stage, make_record
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, box_open
from pokeagent.explorer.press import Presser
from pokeagent.explorer.selector import Selector


class Engine:
    def __init__(self, ctx: ExplorerContext, presser: Presser | None = None, selector: Selector | None = None,
                 decision_log: DecisionLog | None = None) -> None:
        self.ctx = ctx
        self.presser = presser or Presser(ctx)
        self.selector = selector or Selector(default_behaviours())
        self.decision_log = decision_log

    def step(self) -> Decision | None:
        ctx = self.ctx
        decision = self.selector.choose(ctx)
        if decision is None or not decision.button:
            return decision  # nothing to do, or a wait: the step is used without a press
        view = ctx.view
        before, box, battle = (view.m, view.x, view.y), view.box, view.battling
        stage, goals_reached = goal_stage(ctx.goals()), len(ctx.goal_steps)
        self.presser.press(decision.button, "agent", decision.why)
        if decision.after is not None:
            decision.after(ctx)
        if self.decision_log is not None:
            after = ctx.pos()
            box_after = box_open(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))
            outcome = classify_outcome(before, after, decision.button, box_after, len(ctx.goal_steps) > goals_reached)
            self.decision_log.write(make_record(ctx.step, decision.behaviour, decision.rule, decision.button, before,
                                                stage, box, battle, outcome))
        return decision
