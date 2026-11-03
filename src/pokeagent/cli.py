"""pokeagent CLI: ``run`` the agent, ``check-rom``, or print the RAM ``state``.

Usage::

    pokeagent run [--rom PATH] [--backend stub|claude] [--model haiku]
                  [--steps N] [--headless] [--state PATH] [--runs-dir runs]
    pokeagent check-rom [--rom PATH]
    pokeagent state [--rom PATH] [--state PATH]

The ROM path comes from ``--rom``, else ``$POKEAGENT_ROM``, else
``roms/Pokemon Red.gb``. A real backend requires an explicit ``--steps`` so a
run can never burn model calls unbounded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from pokeagent.agent import Agent
from pokeagent.backend import BackendError, ClaudeCliBackend, StubBackend
from pokeagent.emulator import Emulator, PyBoyEmulator
from pokeagent.ram import read_state
from pokeagent.runlog import RunLog

EXPECTED_SHA1 = "EA9BCAE617FDF159B045185467AE58B2E4A48B9A"
DEFAULT_ROM = Path("roms/Pokemon Red.gb")
STEPS_DEFAULT_STUB = 20
BOOT_FRAMES = 60
EXIT_CODES = {"max_steps": 0, "backend_failures": 2, "interrupted": 130}


def _rom_path(args: argparse.Namespace) -> Path:
    """ROM from --rom, else $POKEAGENT_ROM, else the default path."""
    if args.rom:
        return Path(args.rom)
    env = os.environ.get("POKEAGENT_ROM")
    if env:
        return Path(env)
    return DEFAULT_ROM


def _build_emulator(args: argparse.Namespace) -> Emulator:
    """One place that turns args into an Emulator; tests patch this to inject FakeEmulator."""
    return PyBoyEmulator(_rom_path(args), headless=getattr(args, "headless", True))


def _build_backend(args: argparse.Namespace, log: RunLog):
    if args.backend == "claude":
        return ClaudeCliBackend(model=args.model, cwd=log.run_dir)
    return StubBackend()


def _cmd_run(args: argparse.Namespace) -> int:
    steps = args.steps
    if steps is None:
        if args.backend == "claude":
            print(
                "refusing: --steps is required for a real backend "
                "(each step is one claude call)"
            )
            return 2
        steps = STEPS_DEFAULT_STUB
    try:
        emu = _build_emulator(args)
    except (FileNotFoundError, BackendError) as e:
        print(f"error: {e}")
        return 1
    log = RunLog(Path(args.runs_dir))
    try:
        backend = _build_backend(args, log)
    except BackendError as e:
        print(f"error: {e}")
        emu.close()
        return 1
    try:
        if args.state:
            emu.load_state(Path(args.state))
    except (FileNotFoundError, OSError) as e:
        print(f"error: {e}")
        emu.close()
        return 1
    result = Agent(emu, backend, log, max_steps=steps).run()
    return EXIT_CODES.get(result.stop_reason, 1)


def _cmd_check_rom(args: argparse.Namespace) -> int:
    rom = _rom_path(args)
    if not rom.is_file():
        print(f"ROM not found: {rom}")
        return 1
    data = rom.read_bytes()
    sha1 = hashlib.sha1(data).hexdigest().upper()
    print(f"size: {len(data)} bytes")
    print(f"sha1: {sha1}")
    match = sha1 == EXPECTED_SHA1
    print("match" if match else f"mismatch (expected {EXPECTED_SHA1})")
    try:
        emu = _build_emulator(args)
    except (FileNotFoundError, BackendError) as e:
        print(f"boot failed: {e}")
        return 1
    try:
        emu.tick(BOOT_FRAMES)
    except Exception as e:
        print(f"boot failed: {e}")
        return 1
    finally:
        emu.close()
    print("boot ok")
    return 0 if match else 1


def _cmd_state(args: argparse.Namespace) -> int:
    try:
        emu = _build_emulator(args)
    except (FileNotFoundError, BackendError) as e:
        print(f"error: {e}")
        return 1
    try:
        if args.state:
            emu.load_state(Path(args.state))
        emu.tick(BOOT_FRAMES)
        print(read_state(emu).summary())
        return 0
    except Exception as e:
        print(f"error: {e}")
        return 1
    finally:
        emu.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pokeagent",
        description="An agent that plays Pokemon Red on its own through PyBoy.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the agent loop")
    run.add_argument("--rom", metavar="PATH", help="path to the Pokemon Red ROM")
    run.add_argument("--backend", choices=["stub", "claude"], default="stub")
    run.add_argument("--model", default="haiku", help="model for the claude backend")
    run.add_argument("--steps", type=int, default=None, metavar="N",
                     help="step cap; required for a real backend")
    run.add_argument("--headless", action="store_true",
                     help="no SDL2 window, full emulation speed")
    run.add_argument("--state", metavar="PATH", help="snapshot to load after boot")
    run.add_argument("--runs-dir", default="runs", metavar="DIR",
                     help="where run directories are created")
    run.set_defaults(func=_cmd_run)

    check = sub.add_parser("check-rom", help="verify the ROM's SHA-1 and that it boots")
    check.add_argument("--rom", metavar="PATH", help="path to the Pokemon Red ROM")
    check.set_defaults(func=_cmd_check_rom)

    state = sub.add_parser("state", help="boot headless and print the RAM state summary")
    state.add_argument("--rom", metavar="PATH", help="path to the Pokemon Red ROM")
    state.add_argument("--state", metavar="PATH", help="snapshot to load after boot")
    state.set_defaults(func=_cmd_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
