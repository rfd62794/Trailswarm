"""The goal-procedure state dict, held on ``ctx.__dict__`` (same pattern as status_care.of): context.py is at its
300-line ceiling, so these four values are keys here instead of dataclass fields.

- ``seen``    ctx.battles_won value AfterVictory last made a decision for
- ``victory`` the last VictoryDecision (procedures.after_victory_rules), for the runner's pause
- ``steps``   presses spent inside goal procedures this run (RUNNER_STEP_CAP)
- ``run``     the procedure runner's in-flight state (NOT ctx.proc: that is the menu-task one)
"""
from __future__ import annotations

_DEFAULTS = {"seen": 0, "victory": None, "steps": 0, "run": None}


def of(ctx) -> dict:
    """The run's procedure state, created with its defaults on first use."""
    st = ctx.__dict__.get("_procedure_state")
    if st is None:
        st = ctx.__dict__["_procedure_state"] = dict(_DEFAULTS)
    return st
