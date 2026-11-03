"""Make a baseline save state: mash through the Pokemon Red intro until the player stands in the bedroom.

    uv run python tools/make_baseline.py                # writes baselines/bedroom.state + bedroom.png
    uv run python tools/make_baseline.py --visible      # watch it happen

The intro is: title screen (START/A), menu (A on NEW GAME), Oak's speech (A...), player name menu
(DOWN then A picks the preset "RED"; START confirms if a keyboard opened), rival name (same), more
speech, then the bedroom. The press cycle below covers all of those without needing to know which
screen is up. We stop when the believed map-id byte (0xD35E, unverified) reads 0x26 = REDS_HOUSE_2F
and stays there for a few presses, then save the state and a screenshot to look at.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.emulator import Button, PyBoyEmulator  # noqa: E402
from pokeagent.ram import RAM_MAP, read_state  # noqa: E402

CYCLE = [Button.A, Button.A, Button.A, Button.A, Button.DOWN, Button.A, Button.START, Button.B]
BEDROOM_MAP = 0x26


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", default=os.environ.get("POKEAGENT_ROM", "roms/Pokemon Red.gb"))
    ap.add_argument("--out", default="baselines/bedroom")
    ap.add_argument("--max-presses", type=int, default=800)
    ap.add_argument("--visible", action="store_true")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    emu = PyBoyEmulator(Path(a.rom), headless=not a.visible)
    try:
        emu.tick(180)
        announced = False
        for i in range(a.max_presses):
            btn = CYCLE[i % len(CYCLE)]
            emu.press(btn)
            if i % 25 == 0:
                print(f"press {i:4} {btn.name:5} -> {read_state(emu).summary()}")
            if emu.read(RAM_MAP["map_id"]) != BEDROOM_MAP:
                continue
            if not announced:
                print(f"map byte reads bedroom after press {i}; player data is set during the intro, "
                      f"so now checking for control: can RIGHT move the player?")
                announced = True
            # The map/pos bytes are filled in before Oak's speech ends. Control = a RIGHT press changes X.
            x0 = emu.read(RAM_MAP["player_x"])
            emu.press(Button.RIGHT)
            if emu.read(RAM_MAP["player_x"]) == x0:
                continue
            emu.press(Button.LEFT)  # step back to the spawn tile
            emu.tick(60)
            emu.save_state(out.with_suffix(".state"))
            emu.screenshot().convert("RGB").save(out.with_suffix(".png"))
            print(f"in control after {i + 1} presses (RIGHT moved x {x0}->{x0 + 1}): {read_state(emu).summary()}")
            print(f"wrote {out.with_suffix('.state')} and {out.with_suffix('.png')}")
            return 0
        print("gave up: bedroom map id never stabilised (addresses are unverified; check the screenshot)")
        emu.screenshot().convert("RGB").save(out.with_suffix(".failed.png"))
        return 1
    finally:
        emu.close()


if __name__ == "__main__":
    raise SystemExit(main())
