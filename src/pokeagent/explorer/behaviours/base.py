"""The behaviour interface: a named policy fragment with a start condition, one press, a termination and a failure."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from pokeagent.explorer.context import ExplorerContext


@dataclass
class Decision:
    """One behaviour decision: the button to press (``""`` = this step is consumed without a press)."""

    button: str
    rule: str
    why: str = ""
    behaviour: str = ""  # filled in by the Selector
    after: Callable[["ExplorerContext"], None] | None = None  # runs right after the press (e.g. grading a replay)
    driver: str = ""  # who drove the press when it is not the plain rule ("par" = par_follow); written to the decision line


class Behaviour(Protocol):
    name: str

    def applies(self, ctx: "ExplorerContext") -> bool:
        """Start condition: should this behaviour be consulted now?"""
        ...

    def step(self, ctx: "ExplorerContext") -> Decision | None:
        """One press (or a no-press Decision). None = nothing to do: the selector asks the next behaviour."""
        ...

    def done(self, ctx: "ExplorerContext") -> bool:
        """Termination: the thing this behaviour was doing has finished."""
        ...

    def failed(self, ctx: "ExplorerContext") -> bool:
        """Gave up: a cap was hit or the path is blocked."""
        ...


class BehaviourBase:
    """Defaults: done once it no longer applies; never failed."""

    name = ""

    def applies(self, ctx: "ExplorerContext") -> bool:
        raise NotImplementedError

    def step(self, ctx: "ExplorerContext") -> Decision | None:
        raise NotImplementedError

    def done(self, ctx: "ExplorerContext") -> bool:
        return not self.applies(ctx)

    def failed(self, ctx: "ExplorerContext") -> bool:
        return False


def no_press(rule: str, why: str = "") -> Decision:
    """The step is used up (a wait, a pause, a bookkeeping turn) but no button is pressed."""
    return Decision("", rule, why)
