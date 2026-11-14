"""Record a RAM-labelled vision dataset by playing a game headless.

    uv run python tools/vision_record.py --game pokemon-red --rom "roms/Pokemon Red.gb" \
        --state <path> --presses 2000 --seed 1 [--script file.json] [--out runs/vision/pokemon-red] \
        [--max-mb 200] [--sample-every 8] [--run name]

Writes runs/vision/<game>/ (local only, gitignored). Imports no PyBoy at module level so tests can
import it; the emulator import lives in main().
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.vision.driver import DIRECTIONS, RandomWalkDriver, ScriptDriver
from pokeagent.vision.positions import PositionLog
from pokeagent.vision.record import record
from pokeagent.vision.sources import get_source
from pokeagent.vision.store import Store


def out_in_runs(out: Path, cwd: Path) -> bool:
    """``out`` must resolve inside a ``runs`` directory under the cwd: the dataset stays local,
    never a tracked path."""
    try:
        rel = out.resolve().relative_to(cwd.resolve())
    except ValueError:
        return False
    return rel.parts[:1] == ("runs",) or "runs" in rel.parts[:-1]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Record a RAM-labelled vision dataset headless.")
    ap.add_argument("--game", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--state")
    ap.add_argument("--script")
    ap.add_argument("--presses", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--max-mb", type=int, default=200)
    ap.add_argument("--sample-every", type=int, default=8)
    ap.add_argument("--run", default="run")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    source = get_source(a.game)                      # raises a clear error for an unknown game
    out = Path(a.out) if a.out else Path("runs") / "vision" / a.game
    if not out_in_runs(out, Path.cwd()):
        print(f"error: --out {out} is not inside a runs directory under {Path.cwd()}", file=sys.stderr)
        return 2
    driver = ScriptDriver(a.script) if a.script else RandomWalkDriver(a.seed, a.presses, DIRECTIONS)
    state = a.state or getattr(driver, "start_state", None)
    from pokeagent.emulator import Button, PyBoyEmulator   # PyBoy only inside main
    emu = PyBoyEmulator(Path(a.rom), headless=True)        # never a window
    try:
        emu.tick(60)
        if state:
            emu.load_state(Path(state))
            emu.tick(30)
        else:
            for name, hold, settle in source.boot_presses:
                emu.press(Button(name), hold, settle)
        store = Store(out, max_bytes=a.max_mb * 1_000_000)
        store.meta.update(game=a.game, label_source=source.name, sample_every=a.sample_every)
        positions = PositionLog(out)
        counters = record(emu, source, store, positions, driver.iter_presses(),
                          sample_every=a.sample_every, run=a.run)
        positions.close()
        store.flush()
        print(f"{counters} bytes={store.bytes} out={out}")
        return 0
    finally:
        emu.close()


if __name__ == "__main__":
    sys.exit(main())
