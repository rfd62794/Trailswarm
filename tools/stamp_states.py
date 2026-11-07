"""Stamp RAM fingerprints (pokeagent.statefp) beside save states that lack one - checkpoints written before the stamp existed.

    uv run python tools/stamp_states.py runs/checkpoints            # stamp every *.state without a .fp.json (ONE headless emulator)
    uv run python tools/stamp_states.py runs/checkpoints --force    # re-stamp all
    uv run python tools/stamp_states.py runs/checkpoints --dry-run  # list what would be stamped

A stamped ship-stage state whose respawn is behind Vermilion is then refused by the curriculum (tools/seg_store.refusal).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokeagent import statefp  # noqa: E402


def stamp_all(emu, states, force: bool = False) -> list[Path]:
    """Load each state into ``emu`` and write its fingerprint; returns the states stamped. A state that will not load is skipped."""
    done = []
    for p in states:
        if not force and not statefp.is_organic(p):
            continue  # an edited/promoted state keeps its lineage stamp (a re-stamp would drop the lineage record)
        if statefp.sidecar(p).exists() and not force:
            continue
        try:
            emu.load_state(p)
        except Exception as e:  # noqa: BLE001
            print(f"skip {p}: {e!r}")
            continue
        statefp.stamp(emu, p, source_run=None)
        done.append(p)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", type=Path)
    ap.add_argument("--rom", type=Path, default=ROOT / "roms" / "Pokemon Red.gb")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    states = sorted(a.dir.glob("*.state"))
    todo = [p for p in states if a.force or not statefp.sidecar(p).exists()]
    if a.dry_run or not todo:
        print("\n".join(map(str, todo)) or "nothing to stamp")
        return 0
    from pokeagent.emulator import PyBoyEmulator
    emu = PyBoyEmulator(a.rom, headless=True)
    try:
        done = stamp_all(emu, todo, a.force)
    finally:
        emu.close()
    print(f"stamped {len(done)} of {len(states)} states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
