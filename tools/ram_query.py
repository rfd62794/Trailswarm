"""Look up RAM labels: by name (substring), address or region; optionally read live values from a state.

    uv run python tools/ram_query.py wPartyMon1            # name
    uv run python tools/ram_query.py 0xD16B                # address (every label covering it)
    uv run python tools/ram_query.py battle --limit 20     # region
    uv run python tools/ram_query.py wPartyMon1 --state runs/checkpoints/beat_brock.state
    uv run python tools/ram_query.py --regions             # label counts per region
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from pokeagent.ram_lookup import describe, load_map, query, regions  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", help="name substring, 0xADDR, or region")
    ap.add_argument("--state", type=Path, help="read live values from this save state")
    ap.add_argument("--rom", type=Path, default=ROOT / "roms" / "Pokemon Red.gb")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--regions", action="store_true")
    args = ap.parse_args(argv)
    entries = load_map()
    if args.regions or not args.what:
        for region, n in regions(entries).items():
            print(f"{region:12s} {n}")
        return 0
    hits = query(entries, args.what)
    emu = None
    if args.state:
        from pokeagent.emulator import PyBoyEmulator
        emu = PyBoyEmulator(args.rom)
        emu.load_state(args.state)
        emu.tick(2)
    try:
        for e in hits[: args.limit]:
            print(describe(e, emu))
    finally:
        if emu:
            emu.close()
    print(f"({len(hits)} match{'es' if len(hits) != 1 else ''})", file=sys.stderr)
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
