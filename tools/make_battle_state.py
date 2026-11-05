"""Generate baselines/battle.state: a savestate taken the moment a wild battle starts.

    uv run python tools/make_battle_state.py [--from runs/checkpoints/to_route1.state]

Loads a route checkpoint, walks randomly until wIsInBattle (0xD057) != 0, then
saves the state. Requires a party (0xD163 > 0) so the battle actually engages.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rl_env import ACTIONS
from pokeagent.emulator import PyBoyEmulator


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="runs/checkpoints/to_route1.state")
    ap.add_argument("--out", default="baselines/battle.state")
    ap.add_argument("--tries", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    emu = PyBoyEmulator(Path("roms/Pokemon Red.gb"), headless=True)
    emu.load_state(Path(a.src))
    emu.tick(60)
    rng = random.Random(a.seed)
    for i in range(a.tries):
        if emu.read(0xD057) != 0:
            print(f"battle engaged after {i} presses (flag=0x{emu.read(0xD057):02X}, "
                  f"party={emu.read(0xD163)})")
            Path(a.out).parent.mkdir(exist_ok=True)
            emu.save_state(Path(a.out))
            print(f"saved {a.out}")
            return 0
        emu.press(ACTIONS[rng.randrange(4)], hold_frames=8, settle_frames=8)  # walk only
        if i % 200 == 0:
            print(f"  {i} presses, no battle yet", flush=True)
    print("no battle triggered; try another source state or more tries", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
