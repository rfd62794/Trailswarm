"""Selector: each step, ask the behaviours in order and run the first that applies and has something to do."""
from __future__ import annotations

from typing import Iterable

from pokeagent.explorer.behaviours.base import Behaviour, Decision
from pokeagent.explorer.context import ExplorerContext


class Selector:
    def __init__(self, behaviours: Iterable[Behaviour]) -> None:
        self.behaviours: list[Behaviour] = list(behaviours)

    def choose(self, ctx: ExplorerContext) -> Decision | None:
        """One policy step. A behaviour whose ``step`` returns None passes to the next applicable one, so
        bookkeeping behaviours (guards, the Mom-heal check) can run every step without pressing."""
        ctx.bv = None
        ctx.refresh()
        for behaviour in self.behaviours:
            if behaviour.applies(ctx):
                decision = behaviour.step(ctx)
                if decision is not None:
                    decision.behaviour = behaviour.name
                    return decision
        return None

    def first_applicable(self, ctx: ExplorerContext) -> Behaviour | None:
        """The first behaviour whose start condition holds (no step is run)."""
        ctx.refresh()
        return next((b for b in self.behaviours if b.applies(ctx)), None)
