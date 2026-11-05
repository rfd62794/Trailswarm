"""Lean-environment step rate for RL feasibility.

    uv run python tools/env_rate.py [--steps 2000]

Bare PyBoy + one RAM read per step: no planner, no map memory, no logging.
Reports how fast a random policy could run at three frame budgets, which sets
the real cost of RL experiments (the explorer's ~11 steps/s includes planning).
"""
from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

from pokeagent.emulator import Button, PyBoyEmulator

ACTIONS = [Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT, Button.A, Button.B]


def bench(emu, steps: int, fn, label: str, state: Path | None) -> None:
    if state is not None and state.exists():
        emu.load_state(state)
        emu.tick(300)
    t0 = time.time()
    for _ in range(steps):
        fn()
        emu.read(0xD361)  # one RAM read per step, like a real observation
    dt = time.time() - t0
    print(f"{label}: {steps} steps in {dt:.1f}s = {steps / dt:.1f} steps/s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default="baselines/bedroom.state")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    random.seed(a.seed)
    state = Path(a.state)
    emu = PyBoyEmulator(Path(a.rom), headless=True)
    try:
        emu.tick(300)
        bench(emu, a.steps, lambda: emu.tick(1), "raw frames (tick 1)", state)
        bench(emu, a.steps, lambda: emu.tick(4), "agent pacing (tick 4/step)", state)
        bench(emu, a.steps, lambda: emu.press(random.choice(ACTIONS)),
              "full press (hold 8 + settle 16)", state)
        bench(emu, a.steps, lambda: emu.press(random.choice(ACTIONS), hold_frames=1, settle_frames=1),
              "RL-min press (hold 1 + settle 1)", state)
    finally:
        emu.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
