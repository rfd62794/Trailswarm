"""Boot a Gen 1 ROM from power-on through the intro (default preset names) to the bedroom; save a stamped state.

    uv run python tools/make_intro_state.py --rom ROM --out runs/pokemon-blue/checkpoints/bedroom.state

Why: a game's states are its own (Blue never loads a Red state), so a new family member needs its own bedroom
state before any hands-off run. Measured 2026-11-12 on Blue: 138 presses, controllable at (3,6) on map 0x26.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.emulator import Button, PyBoyEmulator
from pokeagent.explorer.perceive import frame_lines
from pokeagent.statemeta import sidecar, write_state

TILEMAP, MAP, PX, PY = 0xC3A0, 0xD35E, 0xD362, 0xD361
BEDROOM = 0x26


def screen(emu) -> str:
    return " | ".join(frame_lines(emu.read_range(TILEMAP, 360)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-presses", type=int, default=600)
    a = ap.parse_args(argv)
    emu = PyBoyEmulator(a.rom, headless=True)
    print(f"game: {emu.game.key}")
    emu.tick(600)
    quiet = 0
    for i in range(a.max_presses):
        text = screen(emu)
        if "NEW NAME" in text:
            emu.press(Button.DOWN)
            emu.press(Button.A)
            continue
        if emu.read(MAP) == BEDROOM and not text:
            quiet += 1
            if quiet >= 4:
                break
            emu.tick(60)
            continue
        quiet = 0
        emu.press(Button.START if i % 7 == 0 and emu.read(MAP) == 0 else Button.A)
    else:
        print(f"gave up: map={emu.read(MAP):#x} screen={screen(emu)!r}")
        return 1
    x, y = emu.read(PX), emu.read(PY)
    # save BEFORE probing, so the state sits exactly where the intro left the player; the probe only proves control
    write_state(emu, a.out, segment="bedroom", note=f"intro with preset names, {emu.game.key}")
    moved = False
    for b in (Button.LEFT, Button.RIGHT, Button.UP, Button.DOWN):  # any one open direction proves control
        emu.press(b); emu.press(b)  # the first press may only turn
        if (emu.read(PX), emu.read(PY)) != (x, y):
            moved = True
            break
    print(f"bedroom reached after {i} presses at ({x},{y}); controllable={moved}")
    if not moved:
        for p in (Path(a.out), Path(sidecar(a.out))):  # write_state also wrote a sidecar beside the state
            p.unlink(missing_ok=True)
        return 1
    print(f"saved {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
