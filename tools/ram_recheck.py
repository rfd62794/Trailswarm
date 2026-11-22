"""Verify over time: re-check ram_map sym-tier entries cheaply against saved states by running the
pure ramlab invariants over one WRAM snapshot per state.

    uv run python tools/ram_recheck.py --rom "roms/Pokemon Red.gb" --states tests/fixtures/rom_states [--game pokemon-red] [--apply]

Dry run by default (writes nothing). A `sym` entry is promoted to `verified` only when it has at
least 2 ok states and 0 fail, and only with --apply. It never demotes: a FAIL prints the state and
reason and the tool exits 1 with nothing written; the controller decides whether the entry becomes
a caveat. Without the ROM it prints `skipped: no ROM` and exits 0.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ram_map import write_map  # noqa: E402

from pokeagent.ramlab import invariants, trust  # noqa: E402
from pokeagent.ramlab.games import map_path_for  # noqa: E402
from pokeagent.ramlab.labels import load_entries  # noqa: E402

WRAM_LO, WRAM_LEN = 0xC000, 0x2000


def snapshot_states(emu, state_paths) -> list[tuple[str, bytes]]:
    """(stem, WRAM bytes) per state: load, tick 1 (the tests/rom/rom_helpers.py pattern), snapshot."""
    out = []
    for p in state_paths:
        emu.load_state(Path(p))
        emu.tick(1)
        out.append((Path(p).stem, bytes(emu.read_range(WRAM_LO, WRAM_LEN))))
    return out


def report_and_promote(entries: list[dict], snaps: list[tuple[str, bytes]], *,
                       today: str, apply: bool) -> tuple[list, list]:
    """Print one row per checked entry; collect every FAIL and every eligible promotion.
    Returns (fails, promotions): fails are (entry, check, state, reason); promotions are
    (entry, evidence text)."""
    rep = invariants.evaluate(entries, snaps)
    fails, promos = [], []
    for e in entries:
        checks = rep.get(e["name"])
        if not checks:
            continue
        for cid, c in sorted(checks.items()):
            print(f"{e['name']:30s} {cid:18s} ok {len(c['ok']):<3d} fail {len(c['fail']):<3d} skip {c['skip']:<3d}")
            fails += [(e["name"], cid, s, r) for s, r in c["fail"]]
        if trust.tier_of(e) != "sym" or any(c["fail"] for c in checks.values()):
            continue
        cid, c = max(checks.items(), key=lambda kv: len(kv[1]["ok"]))
        if len(c["ok"]) >= 2:
            ev = (f"invariant {cid} held in {len(c['ok'])}/{len(snaps)} states ({', '.join(c['ok'])}) "
                  f"on {today}, tools/ram_recheck.py")
            promos.append((e, ev))
    return fails, promos


def recheck(emu, state_paths, entries: list[dict], *, today: str, apply: bool, map_path: Path | None = None) -> int:
    snaps = snapshot_states(emu, state_paths)
    fails, promos = report_and_promote(entries, snaps, today=today, apply=apply)
    for e, ev in promos:
        print(f"{'promote' if apply else 'would promote'} {e['name']}: {ev}")
        if apply:
            trust.promote_verified(e, ev)
    for name, cid, s, r in fails:
        print(f"FAIL {name} [{cid}] {s}: {r}")
    if fails:
        print(f"{len(fails)} invariant failure(s); nothing written")
        return 1
    if apply and promos:
        problems = trust.validate(entries)
        if problems:
            print("trust validation failed after promotion:")
            print("\n".join(f"  - {p}" for p in problems))
            return 1
        write_map(map_path, entries)
        print(f"{len(promos)} promoted -> {map_path}")
    elif apply:
        print("nothing to promote")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", type=Path, default=ROOT / "roms" / "Pokemon Red.gb")
    ap.add_argument("--states", type=Path, default=ROOT / "tests" / "fixtures" / "rom_states")
    ap.add_argument("--game", default="pokemon-red")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not a.rom.is_file():
        print("skipped: no ROM")
        return 0
    entries = load_entries(map_path_for(a.game))
    from pokeagent.emulator import PyBoyEmulator
    emu = PyBoyEmulator(a.rom, headless=True)
    try:
        return recheck(emu, sorted(a.states.glob("*.state")), entries,
                       today=date.today().isoformat(), apply=a.apply, map_path=map_path_for(a.game))
    finally:
        emu.close()


if __name__ == "__main__":
    raise SystemExit(main())
