"""TrainingController, slice 1: a SHADOW owner. observe() re-derives the training values and compares them with the
old flags; a difference is logged (one line per field per RATE_STEPS) and kept in ``mismatches`` (bounded to the last MAX_MISMATCHES). It never writes ctx
flags and never raises, so decisions.jsonl cannot change."""
from __future__ import annotations

import logging
from collections import deque

from pokeagent.explorer.training_ctl import adapters
from pokeagent.explorer.training_ctl.state import TrainingState

log = logging.getLogger(__name__)
RATE_STEPS = 500  # per field: at most one log line this often
MAX_MISMATCHES = 200  # only the most recent mismatches are kept (a persistent one would otherwise grow without bound)


class TrainingController:
    def __init__(self) -> None:
        self.mismatches: deque[tuple[int, str, tuple]] = deque(maxlen=MAX_MISMATCHES)   # (step, field, (old, shadow)) - tests assert this is empty
        self._last_logged: dict[str, int] = {}

    def observe(self, ctx) -> TrainingState | None:
        try:
            old, shadow = adapters.old_flags(ctx), adapters.derived(ctx)
            ctx.__dict__["training"] = shadow
            for name, pair in old.diff(shadow).items():
                self.mismatches.append((ctx.step, name, pair))
                if ctx.step - self._last_logged.get(name, -RATE_STEPS) >= RATE_STEPS:
                    self._last_logged[name] = ctx.step
                    log.warning("training_ctl shadow mismatch step %s %s: old=%r shadow=%r", ctx.step, name, *pair)
            return shadow
        except Exception as e:  # noqa: BLE001  shadow only: a read failure must never reach the run
            step = getattr(ctx, "step", 0)
            if not isinstance(step, int):
                step = 0
            if step - self._last_logged.get("observe_failed", -RATE_STEPS) >= RATE_STEPS:
                self._last_logged["observe_failed"] = step
                log.warning("training_ctl observe failed (%r)", e)
            return None
