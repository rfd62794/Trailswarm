"""The bounded agent loop: read state, ask the backend, press a button, log it.

Stops on the step cap, too many consecutive failed steps, or Ctrl+C. Whatever
happens it writes a final snapshot and summary and closes the emulator.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pokeagent.backend import Backend, BackendError
from pokeagent.console import print_step, print_summary
from pokeagent.decision import Decision, parse_reply
from pokeagent.emulator import Button, Emulator
from pokeagent.prompt import build_prompt
from pokeagent.ram import read_state
from pokeagent.runlog import RunLog


@dataclass(frozen=True)
class RunResult:
    steps: int
    stop_reason: str  # "max_steps" | "backend_failures" | "interrupted"
    run_dir: Path
    failures: int


class Agent:
    """Drives the Emulator/Backend pair for at most ``max_steps`` steps.

    A step whose Decision carries an error (backend failure or unparseable
    reply) counts as a failure; ``max_consecutive_failures`` in a row ends the
    run with ``stop_reason="backend_failures"``.
    """

    def __init__(
        self,
        emu: Emulator,
        backend: Backend,
        log: RunLog,
        *,
        max_steps: int,
        snapshot_every: int = 10,
        max_consecutive_failures: int = 3,
        out: TextIO = sys.stdout,
    ) -> None:
        self.emu = emu
        self.backend = backend
        self.log = log
        self.max_steps = max_steps
        self.snapshot_every = snapshot_every
        self.max_consecutive_failures = max_consecutive_failures
        self.out = out

    def run(self) -> RunResult:
        steps = 0
        failures = 0
        consecutive = 0
        stop_reason = "max_steps"
        try:
            for step in range(1, self.max_steps + 1):
                state = read_state(self.emu)
                prompt = build_prompt(
                    state, self.log.recent(), self.log.notes(), step, self.max_steps
                )
                start = time.perf_counter()
                try:
                    raw = self.backend.choose(prompt)
                    decision = parse_reply(raw)
                except BackendError as e:
                    decision = Decision("NONE", error=str(e))
                backend_ms = int((time.perf_counter() - start) * 1000)
                self.emu.press(Button[decision.button])
                self.log.append(
                    {
                        "step": step,
                        "state": state.as_dict(),
                        "button": decision.button,
                        "thinking": decision.thinking,
                        "note": decision.note,
                        "error": decision.error,
                        "backend_ms": backend_ms,
                    }
                )
                print_step(
                    step,
                    self.max_steps,
                    state,
                    decision,
                    error_ms=backend_ms if decision.error else None,
                    out=self.out,
                )
                if decision.note:
                    self.log.add_note(decision.note)
                steps = step
                if decision.error:
                    failures += 1
                    consecutive += 1
                else:
                    consecutive = 0
                if self.snapshot_every and step % self.snapshot_every == 0:
                    self.emu.save_state(self.log.state_path(step))
                if consecutive >= self.max_consecutive_failures:
                    stop_reason = "backend_failures"
                    break
        except KeyboardInterrupt:
            stop_reason = "interrupted"
        finally:
            result = RunResult(
                steps=steps,
                stop_reason=stop_reason,
                run_dir=self.log.run_dir,
                failures=failures,
            )
            try:
                self.emu.save_state(self.log.state_path(steps))
            except Exception as e:
                print(f"warning: final snapshot failed: {e}", file=self.out)
            self.log.write_summary(result)
            print_summary(result, self.out)
            self.emu.close()
        return result
