"""TrainingController, slice 1: a SHADOW owner. observe() re-derives the training values and compares them with the
old flags; a difference is logged (one line per field per RATE_STEPS) and kept in ``mismatches``. It never writes ctx
flags and never raises, so decisions.jsonl cannot change."""
from __future__ import annotations

import logging

from pokeagent.explorer.training_ctl import adapters
from pokeagent.explorer.training_ctl.state import TrainingState

log = logging.getLogger(__name__)
RATE_STEPS = 500  # per field: at most one log line this often


class TrainingController:
    def __init__(self) -> None:
        self.mismatches: list[tuple[int, str, tuple]] = []   # (step, field, (old, shadow)) - tests assert this is empty
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
            log.warning("training_ctl observe failed (%r)", e)
            return None
