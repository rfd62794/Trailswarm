"""Build reusable emulator checkpoints from an existing savestate.

Examples:
    uv run python tools/make_state.py --src runs/checkpoints/deliver_parcel.state \
        --out runs/checkpoints/deliver_parcel_closed.state --clear-dialog

    uv run python tools/make_state.py --src runs/checkpoints/deliver_parcel_closed.state \
        --out runs/checkpoints/viridian_old_man.state --goto 1:18:11 --press UP

The walker uses the learned map graph in runs/maps.json. It is deliberately
conservative: it clears text boxes, optionally fights wild battles with A, and
aborts when it cannot verify progress.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pokeagent.emulator import Button, PyBoyEmulator
from pokeagent.explorer import frame_lines
from pokeagent.ram import read_state

sys.path.insert(0, str(Path(__file__).parent))
from explore_plan import WorldGraph  # noqa: E402

TILEMAP = 0xC3A0
BATTLE = 0xD057
PARTY_COUNT = 0xD163
PARTY_HP = 0xD16C
PARTY_STRIDE = 44


def _button(name: str) -> Button:
    try:
        return Button[name.upper()]
    except KeyError as error:
        raise argparse.ArgumentTypeError(f"unknown button: {name}") from error


def _u16(emu, address: int) -> int:
    return (emu.read(address) << 8) | emu.read(address + 1)


def party_hp(emu) -> int:
    return sum(_u16(emu, PARTY_HP + i * PARTY_STRIDE)
               for i in range(min(6, emu.read(PARTY_COUNT))))


def clear_dialog(emu, limit: int = 600) -> None:
    quiet = 0
    for _ in range(limit):
        tm = emu.read_range(TILEMAP, 360)
        if not frame_lines(tm):
            quiet += 1
            if quiet >= 6:  # scripted scenes often pause briefly before the next page
                return
            emu.tick(30)
            continue
        quiet = 0
        emu.press(Button.B if 0xED in tm else Button.A, hold_frames=4, settle_frames=8)
    raise RuntimeError("dialog/menu did not clear")


def fight_battle(emu, limit: int = 400) -> None:
    for _ in range(limit):
        if emu.read(BATTLE) == 0:
            if party_hp(emu) == 0:
                raise RuntimeError("blackout while building state")
            return
        emu.press(Button.A, hold_frames=8, settle_frames=8)
    raise RuntimeError("battle did not finish")


def goto(emu, maps_path: Path, target: tuple[int, int, int], *, max_presses: int,
         fight: bool) -> None:
    import json
    graph = WorldGraph(json.loads(maps_path.read_text()).get("maps", {}))
    stuck = 0
    for _ in range(max_presses):
        state = read_state(emu)
        if (state.map_id, state.x, state.y) == target:
            return
        if emu.read(BATTLE) != 0:
            if not fight:
                raise RuntimeError(f"battle encountered at {(state.map_id, state.x, state.y)}")
            fight_battle(emu)
            continue
        tm = emu.read_range(TILEMAP, 360)
        if frame_lines(tm):
            clear_dialog(emu)
            continue
        path = graph.path((state.map_id, state.x, state.y), lambda node: node == target)
        if not path:
            raise RuntimeError(f"no learned path from {(state.map_id, state.x, state.y)} to {target}")
        emu.press(Button[path[0]], hold_frames=8, settle_frames=8)
        after = read_state(emu)
        stuck = 0 if (after.map_id, after.x, after.y) != (state.map_id, state.x, state.y) else stuck + 1
        if stuck > 12:
            raise RuntimeError(f"walker made no progress at {(state.map_id, state.x, state.y)}")
    raise RuntimeError(f"goto {target} exceeded {max_presses} presses")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="source savestate")
    parser.add_argument("--out", required=True, help="checkpoint to write")
    parser.add_argument("--clear-dialog", action="store_true", help="clear text/menus after loading")
    parser.add_argument("--goto", metavar="MAP:X:Y", help="walk to a learned tile")
    parser.add_argument("--press", action="append", default=[], type=_button,
                        help="extra button to press after --goto; repeat as needed")
    parser.add_argument("--expect", metavar="MAP:X:Y", help="final tile to verify after --press")
    parser.add_argument("--fight", action="store_true", help="fight wild battles with A while walking")
    parser.add_argument("--maps", default="runs/maps.json")
    parser.add_argument("--max-presses", type=int, default=1200)
    parser.add_argument("--rom", default="roms/Pokemon Red.gb")
    args = parser.parse_args()

    def parse_tile(value, flag):
        if not value:
            return None
        parts = value.split(":")
        if len(parts) != 3:
            parser.error(f"{flag} must be MAP:X:Y")
        return tuple(int(part, 0) for part in parts)

    target = parse_tile(args.goto, "--goto")
    expected = parse_tile(args.expect, "--expect")

    emu = PyBoyEmulator(Path(args.rom), headless=True)
    try:
        emu.load_state(Path(args.src))
        emu.tick(60)
        if args.clear_dialog:
            clear_dialog(emu)
        if target is not None:
            goto(emu, Path(args.maps), target, max_presses=args.max_presses, fight=args.fight)
        for button in args.press:
            emu.press(button, hold_frames=8, settle_frames=12)
        emu.tick(30)
        verify = expected or target
        if verify is not None:
            state = read_state(emu)
            if (state.map_id, state.x, state.y) != verify:
                raise RuntimeError(f"expected {verify}, got {(state.map_id, state.x, state.y)}")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        emu.save_state(out)
        print(f"saved {out} at {read_state(emu).summary()}")
        return 0
    finally:
        emu.close()


if __name__ == "__main__":
    raise SystemExit(main())
