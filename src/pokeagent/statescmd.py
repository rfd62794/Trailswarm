"""``pokeagent states``: the save-state ledger CLI - ``list``, ``check``, ``restamp``, ``retire``.

Handlers take parsed args and return an exit code so tests call them without a process. The ledger is
``pokeagent.statelog`` (pure JSON over the ``.fp.json`` sidecars); ``restamp`` delegates to ``tools/stamp_states.py``
and needs the ROM unless ``--dry-run``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pokeagent import checkpoint_goals as cg
from pokeagent import statefp, statelog

DEFAULT_DIRS = (Path("runs/checkpoints"), Path("runs/legs/states"))
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROM = ROOT / "roms" / "Pokemon Red.gb"


def make_emulator(rom):
    """The emulator the legal check drives (a seam so tests inject a FakeEmulator)."""
    from pokeagent.emulator import PyBoyEmulator
    return PyBoyEmulator(Path(rom), headless=True)


def _kb_json(name: str) -> dict | None:
    """A kb/ table (rom_tables.json, items.json, hm_compat.json) or None when absent/unreadable."""
    try:
        return json.loads((ROOT / "kb" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dirs(args) -> list[Path]:
    return [Path(d) for d in args.dir] if getattr(args, "dir", None) else list(DEFAULT_DIRS)


def _entries(dirs) -> list[statelog.Entry]:
    return [e for d in dirs for e in statelog.entries(d)]


def _party(fp: dict) -> str:
    return " ".join(f"{m[0]} L{m[1]}" for m in fp.get("party") or [])


def cmd_list(args) -> int:
    """One row per state: name, map, x,y, respawn, party, HP%, money, source run, status (--bad adds the reason)."""
    for e in _entries(_dirs(args)):
        fp = e.fp
        if args.map is not None and fp.get("map") != args.map:
            continue
        reason = statelog.bad(e)
        if args.bad and reason is None:
            continue
        g = lambda k: str(fp.get(k, "?"))
        pos = f"{fp.get('x', '?')},{fp.get('y', '?')}" if fp else "?"
        try:
            hp = f"{statefp.party_hp_fraction(fp):.0%}" if fp.get("party") else "?"
            party = _party(fp) or "?"
        except statelog.CORRUPT:
            hp = party = "?"
        row = [e.path.name, g("map"), pos, g("respawn"), party, hp, g("money"), g("source_run"), statelog.status(e)]
        if args.bad:
            row.append(reason or "")
        print("\t".join(row))
    return 0


def _legal(args) -> int:
    """``states check --legal``: legality.check every state in the dirs; --envelope adds the organic-envelope verdicts."""
    from pokeagent import envelope, legality
    dirs = _dirs(args)
    kb, catalog, hm = _kb_json("rom_tables.json"), _kb_json("items.json"), _kb_json("hm_compat.json")
    rom_bytes = Path(args.rom).read_bytes() if args.rom and Path(args.rom).exists() else None
    env = envelope.build(dirs) if getattr(args, "envelope", False) else None
    emu, fail = None, False
    try:
        for e in _entries(dirs):
            if emu is None:
                emu = make_emulator(Path(args.rom) if args.rom else DEFAULT_ROM)
            emu.load_state(e.path)
            r = legality.check(emu, kb, catalog=catalog, hm=hm, rom=rom_bytes)
            fail = fail or not r.ok
            for line in ([f"{e.path.name}\tok"] if r.ok else [f"{e.path.name}\t{v}" for v in r.violations]):
                print(line)
            for w in r.warnings:
                print(f"{e.path.name}\twarning: {w}")
            if env is not None:
                inside, reasons = envelope.within_envelope(e.fp, envelope.stage_key(e.path.name, e.fp), env)
                for reason in reasons:
                    print(f"{e.path.name}\tenvelope: {reason}")
                if r.ok and not inside:
                    print(f"{e.path.name}\tlegal, unreachable")
    finally:
        if emu is not None:
            emu.close()
    return 1 if fail else 0


def cmd_check(args) -> int:
    """Exit 1 when a ship state (ship-goal stem, or a fingerprint on a ship map) respawns behind Vermilion or has a
    missing/stale sidecar; other bad states are listed but do not fail. ``--legal`` runs the legality checker instead."""
    if getattr(args, "legal", False):
        return _legal(args)
    from pokeagent.explorer.world import SHIP_MAPS
    fail, rows = False, []
    for e in _entries(_dirs(args)):
        reason = statelog.bad(e)
        try:
            ship = e.stem in cg.SHIP_GOALS or e.fp.get("map") in SHIP_MAPS
            behind = e.fp.get("respawn") in cg.BEHIND_VERMILION
        except statelog.CORRUPT:
            ship, behind = e.stem in cg.SHIP_GOALS, False
        if ship and (behind or statelog.status(e) != "fresh"):
            fail = True
            reason = reason or "ship state with respawn behind Vermilion or a missing/stale sidecar"
        if reason:
            rows.append(f"{e.path.name}\t{statelog.status(e)}\t{reason}")
    for r in rows:
        print(r)
    print(f"{len(rows)} bad state(s)" if rows else "no bad states")
    return 1 if fail else 0


def cmd_promote(args) -> int:
    """``states promote END --from START``: promote a legal, in-envelope descendant of an organic-equivalent
    synthetic start to lineage ``promoted``. Exit 1 with the reasons when the promotion does not hold."""
    from pokeagent import envelope, lineage
    end, start = Path(args.path), Path(args.start)
    kb, catalog, hm = _kb_json("rom_tables.json"), _kb_json("items.json"), _kb_json("hm_compat.json")
    rom_bytes = Path(args.rom).read_bytes() if args.rom and Path(args.rom).exists() else None
    emu = make_emulator(Path(args.rom) if args.rom else DEFAULT_ROM)
    try:
        emu.load_state(end)
        ok, reasons = lineage.promote(end, start, emu, kb, catalog=catalog, hm=hm, rom=rom_bytes,
                                      env=envelope.build(_dirs(args)))
    finally:
        emu.close()
    if ok:
        print(f"promoted {end.name} (descended from {start.name})")
        return 0
    for reason in reasons:
        print(f"{end.name}\t{reason}")
    return 1


def cmd_restamp(args) -> int:
    """Delegate to tools/stamp_states.py on each state dir (imported here: tools/ is not a package)."""
    sys.path.insert(0, str(TOOLS_DIR))
    import stamp_states
    flags = ["--force"] * bool(args.force) + ["--dry-run"] * bool(args.dry_run)
    rc = 0
    for d in _dirs(args):
        rc |= stamp_states.main([str(d), *flags])
    return rc


def cmd_retire(args) -> int:
    """Move a state and its sidecars into runs/retired (statelog.retire) and say where it went."""
    if not Path(args.path).is_file():
        print(f"no such state: {args.path}", file=sys.stderr)
        return 1
    dest = statelog.retire(Path(args.path), args.why)
    print(f"retired {Path(args.path).name} -> {dest}")
    return 0


def add_parser(sub) -> None:
    """``pokeagent states <sub> [--dir D ...]``; a repeatable --dir overrides the two default state dirs."""
    p = sub.add_parser("states", help="save-state ledger: list, check, restamp, retire")
    s = p.add_subparsers(dest="states_cmd", required=True)

    def dirs(sp):
        sp.add_argument("--dir", action="append", default=None, metavar="D",
                        help="state dir (repeatable; default runs/checkpoints and runs/legs/states)")

    lp = s.add_parser("list", help="one row per state: name, map, x,y, respawn, party, HP%%, money, source run, status")
    lp.add_argument("--map", type=lambda v: int(v, 0), default=None, metavar="M", help="only states on this map id")
    lp.add_argument("--bad", action="store_true", help="only states statelog.bad flags, with the reason")
    dirs(lp)
    lp.set_defaults(func=cmd_list)

    cp = s.add_parser("check", help="fail when a ship state respawns behind Vermilion or is unstamped/stale")
    cp.add_argument("--legal", action="store_true", help="run the legality checker on every state (exit 1 on any violation)")
    cp.add_argument("--envelope", action="store_true", help="with --legal: also print the organic-envelope verdicts")
    cp.add_argument("--rom", type=Path, default=DEFAULT_ROM, metavar="ROM", help="ROM for the emulator and walk-grid check")
    dirs(cp)
    cp.set_defaults(func=cmd_check)

    pp = s.add_parser("promote", help="promote a legal in-envelope descendant of an organic-equivalent synthetic start")
    pp.add_argument("path", type=Path, metavar="END.state")
    pp.add_argument("--from", dest="start", type=Path, required=True, metavar="START.state")
    pp.add_argument("--rom", type=Path, default=DEFAULT_ROM, metavar="ROM")
    dirs(pp)
    pp.set_defaults(func=cmd_promote)

    rp = s.add_parser("restamp", help="re-run tools/stamp_states.py on the state dirs (needs the ROM unless --dry-run)")
    rp.add_argument("--force", action="store_true", help="re-stamp states that already have a sidecar")
    rp.add_argument("--dry-run", action="store_true", help="list what would be stamped")
    dirs(rp)
    rp.set_defaults(func=cmd_restamp)

    tp = s.add_parser("retire", help="move a state and its sidecars into runs/retired with a reason")
    tp.add_argument("path", type=Path, metavar="PATH")
    tp.add_argument("--why", required=True, metavar="TEXT")
    tp.set_defaults(func=cmd_retire)
