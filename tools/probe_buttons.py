"""Button probe: press each button a few times and record which RAM bytes changed.

A basic, usable-now version of what Hex_Map_Discovery_Directive formalises. Run from the repo root:

    uv run python tools/probe_buttons.py --state runs/<ts>/state_0010.state --repeat 3
    uv run python tools/probe_buttons.py --buttons RIGHT LEFT --idle 4

For every button it snapshots WRAM (0xC000-0xDFFF), presses, snapshots again, `repeat` times, then
reports the addresses that changed on EVERY press of that button and were quiet while idle. Results go to
runs/probe-<timestamp>.jsonl (one line per button) and a summary prints to the console.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.emulator import Button, PyBoyEmulator  # noqa: E402
from pokeagent.ram import RAM_MAP, read_state  # noqa: E402

WRAM_START, WRAM_LEN = 0xC000, 0x2000
NAMES = {addr: name for name, addr in RAM_MAP.items()}


def snapshot(emu) -> bytes:
    return emu.read_range(WRAM_START, WRAM_LEN)


def changed(before: bytes, after: bytes) -> dict[int, tuple[int, int]]:
    return {WRAM_START + i: (b, a) for i, (b, a) in enumerate(zip(before, after)) if b != a}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", default=os.environ.get("POKEAGENT_ROM", "roms/Pokemon Red.gb"))
    ap.add_argument("--state", help="save-state to load after boot")
    ap.add_argument("--buttons", nargs="+", default=["A", "B", "START", "UP", "DOWN", "LEFT", "RIGHT"])
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--idle", type=int, default=3, help="idle snapshots used to learn noisy bytes")
    ap.add_argument("--visible", action="store_true", help="open the PyBoy window while probing")
    ap.add_argument("--runs-dir", default="runs")
    a = ap.parse_args(argv)

    emu = PyBoyEmulator(Path(a.rom), headless=not a.visible)
    out = Path(a.runs_dir) / f"probe-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        emu.tick(120)
        if a.state:
            emu.load_state(Path(a.state))
        print(f"start: {read_state(emu).summary()}")

        noisy: set[int] = set()
        prev = snapshot(emu)
        for _ in range(a.idle):
            emu.tick(24)
            cur = snapshot(emu)
            noisy |= set(changed(prev, cur))
            prev = cur
        print(f"noisy bytes while idle: {len(noisy)}")

        with out.open("a", encoding="utf-8") as fh:
            for name in a.buttons:
                btn = Button[name.upper()]
                consistent: set[int] | None = None
                deltas: dict[int, list[int]] = {}
                for _ in range(a.repeat):
                    before = snapshot(emu)
                    emu.press(btn)
                    after = snapshot(emu)
                    ch = {k: v for k, v in changed(before, after).items() if k not in noisy}
                    consistent = set(ch) if consistent is None else consistent & set(ch)
                    for addr, (b, c) in ch.items():
                        deltas.setdefault(addr, []).append(c - b)
                hits = sorted(consistent or ())
                rec = {
                    "button": btn.name,
                    "state_after": read_state(emu).as_dict(),
                    "consistent": [
                        {"addr": f"0x{x:04X}", "name": NAMES.get(x, ""), "deltas": deltas[x]} for x in hits
                    ],
                }
                fh.write(json.dumps(rec) + "\n")
                shown = ", ".join(
                    f"{h['addr']}{'=' + h['name'] if h['name'] else ''}{h['deltas']}" for h in rec["consistent"][:12]
                )
                print(f"{btn.name:6} -> {len(hits):3} consistent bytes: {shown}{' ...' if len(hits) > 12 else ''}")
        print(f"end:   {read_state(emu).summary()}\nwrote {out}")
    finally:
        emu.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
