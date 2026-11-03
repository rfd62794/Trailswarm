"""``pokeagent hex`` subcommands: WRAM dump/diff/find plus screen-text read.

All subcommands boot headless (``--rom`` as in ``run``, optional ``--state``
snapshot) and close the emulator when done. Tests inject FakeEmulator by
patching ``cli._build_emulator`` like the other command tests.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pokeagent.emulator import Button, Emulator
from pokeagent.hexmap import (
    WRAM_LEN,
    WRAM_START,
    annotate,
    diff,
    exclude_noisy,
    find_consistent,
    snapshot,
)
from pokeagent.names import load_registry
from pokeagent.screentext import read_screen_text

BOOT_FRAMES = 60
IDLE_TICK = 24
BUTTONS = [b.name for b in Button]


def _build(args: argparse.Namespace) -> Emulator:
    """Deferred import: cli.py imports this module to register the parser."""
    from pokeagent import cli

    return cli._build_emulator(args)


def _boot(args: argparse.Namespace) -> Emulator:
    emu = _build(args)
    try:
        if args.state:
            emu.load_state(Path(args.state))
        emu.tick(BOOT_FRAMES)
    except Exception:
        emu.close()
        raise
    return emu


def _parse_range(text: str) -> tuple[int, int]:
    """'D350-D370' -> (0xD350, 0xD370); end is exclusive."""
    lo, _, hi = text.partition("-")
    try:
        return int(lo, 16), int(hi, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"bad range {text!r}: expected HEX-HEX like D350-D370"
        ) from None


def _int_auto(text: str) -> int:
    return int(text, 0)


def _cmd_dump(args: argparse.Namespace) -> int:
    reg = load_registry()
    emu = _boot(args)
    try:
        start, end = args.range
        data = emu.read_range(start, max(0, end - start))
        for off in range(0, len(data), 16):
            chunk = data[off : off + 16]
            addr = start + off
            hexs = " ".join(f"{b:02X}" for b in chunk)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            names = sorted(
                {reg.name_at(addr + i) for i in range(len(chunk))} - {None}
            )
            margin = "  " + " ".join(names) if names else ""
            print(f"{addr:04X}  {hexs:<47}  |{asc}|{margin}")
        return 0
    finally:
        emu.close()


def _cmd_diff(args: argparse.Namespace) -> int:
    reg = load_registry()
    emu = _boot(args)
    try:
        before = snapshot(emu)
        for name in args.press:
            emu.press(Button[name.upper()])
        lines = annotate(diff(before, snapshot(emu)), reg)
        print("\n".join(lines) if lines else "no changes")
        return 0
    finally:
        emu.close()


def _cmd_find(args: argparse.Namespace) -> int:
    reg = load_registry()
    emu = _boot(args)
    try:
        idle_snaps = []
        for _ in range(args.idle):
            emu.tick(IDLE_TICK)
            idle_snaps.append(snapshot(emu))
        snaps = [idle_snaps[-1] if idle_snaps else snapshot(emu)]
        button = Button[args.press.upper()]
        for _ in range(args.repeat):
            emu.press(button)
            snaps.append(snapshot(emu))
        cands = set(find_consistent(snaps, delta=args.delta)) - exclude_noisy(
            idle_snaps
        )
        if not cands:
            print("no consistent addresses")
        for addr in sorted(cands):
            print(f"{addr:04X} {reg.name_at(addr) or '-'}")
        return 0
    finally:
        emu.close()


def _cmd_screen(args: argparse.Namespace) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # é and friends on a cp1252 console
    reg = load_registry()
    emu = _boot(args)
    try:
        rows = read_screen_text(emu, reg)
        print("\n".join(rows) if rows else "(blank screen)")
        return 0
    finally:
        emu.close()


def _guarded(func):
    def inner(args: argparse.Namespace) -> int:
        try:
            return func(args)
        except Exception as e:
            print(f"error: {e}")
            return 1

    return inner


def register(sub) -> None:
    """Attach the ``hex`` subcommand tree to the main CLI's subparsers."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rom", metavar="PATH", help="path to the Pokemon Red ROM")
    common.add_argument("--state", metavar="PATH", help="snapshot to load after boot")

    hexp = sub.add_parser("hex", help="WRAM mapping and screen-text tools")
    hsub = hexp.add_subparsers(dest="hex_command", required=True)

    dump = hsub.add_parser(
        "dump", parents=[common], help="hex-dump a WRAM range with registry names"
    )
    dump.add_argument(
        "--range",
        type=_parse_range,
        default=_parse_range(f"{WRAM_START:X}-{WRAM_START + WRAM_LEN:X}"),
        metavar="HEX-HEX",
        help="address range like D350-D370 (end exclusive)",
    )
    dump.set_defaults(func=_guarded(_cmd_dump))

    d = hsub.add_parser(
        "diff", parents=[common], help="snapshot, press buttons, snapshot, diff"
    )
    d.add_argument(
        "--press",
        action="append",
        required=True,
        choices=BUTTONS,
        metavar="BTN",
        help="button to press; repeatable, pressed in order",
    )
    d.set_defaults(func=_guarded(_cmd_diff))

    f = hsub.add_parser(
        "find", parents=[common], help="addresses that changed on every press"
    )
    f.add_argument("--press", required=True, choices=BUTTONS, metavar="BTN")
    f.add_argument("--repeat", type=int, default=3, metavar="N")
    f.add_argument(
        "--delta",
        type=_int_auto,
        default=None,
        metavar="N",
        help="required per-press change, e.g. 1 for X when walking RIGHT",
    )
    f.add_argument(
        "--idle",
        type=int,
        default=0,
        metavar="N",
        help="idle snapshots first, to subtract timers/RNG",
    )
    f.set_defaults(func=_guarded(_cmd_find))

    s = hsub.add_parser(
        "screen", parents=[common], help="decode the visible tile map to text"
    )
    s.set_defaults(func=_guarded(_cmd_screen))
