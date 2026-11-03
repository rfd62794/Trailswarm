"""What Robert watches while a run plays: one block per step, plus a summary.

Plain ``print`` only, no third-party libraries; ``out`` is injectable so
tests capture the output.
"""

from __future__ import annotations

import sys
from typing import Any, TextIO

from pokeagent.decision import Decision
from pokeagent.ram import GameState


def print_step(
    step: int,
    max_steps: int,
    state: GameState,
    decision: Decision,
    error_ms: int | None = None,
    out: TextIO = sys.stdout,
) -> None:
    """Print one step block: state line, thinking, button (+note), error line."""
    print(f"--- step {step}/{max_steps}  {state.summary()}", file=out)
    print(f"thinking: {decision.thinking}", file=out)
    if decision.note:
        print(f"button:   {decision.button:<11}note: {decision.note}", file=out)
    else:
        print(f"button:   {decision.button}", file=out)
    if decision.error:
        suffix = f" ({error_ms}ms)" if error_ms is not None else ""
        print(f"error:   {decision.error}{suffix}", file=out)


def print_summary(result: Any, out: TextIO = sys.stdout) -> None:
    """End-of-run block: steps taken, stop reason, run directory, failures."""
    print("=== run summary ===", file=out)
    print(f"steps:    {result.steps}", file=out)
    print(f"stop:     {result.stop_reason}", file=out)
    print(f"failures: {result.failures}", file=out)
    print(f"run dir:  {result.run_dir}", file=out)
