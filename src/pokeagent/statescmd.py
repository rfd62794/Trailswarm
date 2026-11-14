"""``pokeagent states``: the save-state ledger CLI - ``list``, ``check``, ``restamp``, ``retire``, ``library``.

Handlers take parsed args and return an exit code so tests call them without a process. The ledger is
``pokeagent.statelog`` (pure JSON over the ``.fp.json`` sidecars); ``restamp`` delegates to ``tools/stamp_states.py``
and needs the ROM unless ``--dry-run``. ``library`` builds/lists/validates the save library
(``runs/states/library.json``) that ``pokeagent.statelib`` maintains.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from pokeagent import checkpoint_goals as cg
from pokeagent import party_rules, statefp, statelib, statelog
from pokeagent.game.paths import default_rom
from pokeagent.game.stores import store_path

# checkpoints is game-scope (a state is ROM-bound); runs/legs/states stays literal - never family-shared.
# POKEAGENT_GAME is read once at import (a process runs one game).
DEFAULT_DIRS = (store_path("runs/checkpoints", scope="game"), Path("runs/legs/states"))
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROM = default_rom(root=ROOT)


def make_emulator(rom):
    """The emulator the legal check drives (a seam so tests inject a FakeEmulator)."""
    from pokeagent.emulator import PyBoyEmulator
    return PyBoyEmulator(Path(rom), headless=True)


def _kb_json(name: str) -> dict | None:
    """A kb/ table (rom_tables.json, items.json, hm_compat.json) or None when absent/unreadable."""
    try:
        return json.loads(store_path(Path("kb") / name, root=ROOT).read_text(encoding="utf-8"))
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
    missing/stale sidecar - or when a state in a checkpoints dir breaks a party rule (``--strict`` fails on any
    violation and on unknown verdicts; unknowns are listed but never fail without it). ``--legal`` runs the
    legality checker instead."""
    if getattr(args, "legal", False):
        return _legal(args)
    from pokeagent.explorer.world import SHIP_MAPS
    strict, kb = getattr(args, "strict", False), _kb_json("rom_tables.json")
    fail, rows = False, []
    for e in _entries(_dirs(args)):
        reason = statelog.bad(e)
        v = party_rules.verdict(e.fp, kb)
        try:
            ship = e.stem in cg.SHIP_GOALS or e.fp.get("map") in SHIP_MAPS
            behind = e.fp.get("respawn") in cg.BEHIND_VERMILION
        except statelog.CORRUPT:
            ship, behind = e.stem in cg.SHIP_GOALS, False
        if ship and (behind or statelog.status(e) != "fresh"):
            fail = True
            reason = reason or "ship state with respawn behind Vermilion or a missing/stale sidecar"
        if v == "violation":
            rows.append(f"{e.path.name}\tviolation\t{'; '.join(party_rules.violations(e.fp, kb))}")
            fail = fail or strict or e.path.parent.name == "checkpoints"
            if reason and reason.startswith("party rule:"):
                reason = None                                # already reported in the violation row
        elif v == "unknown":
            rows.append(f"{e.path.name}\tunknown\tno team recorded or kb tables unavailable")
            fail = fail or strict
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
    vio = party_rules.violations(statefp.read(end) or {}, kb)
    if vio:
        print(f"{end.name}\tparty rule: {'; '.join(vio)}")
        return 1                                             # a violating state cannot become a checkpoint
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


def cmd_library_build(args) -> int:
    """``states library build``: index every checkpoint and leg state into the save library and print the counts
    per tier and per verdict, plus the legs retention would drop (it drops nothing on disk)."""
    doc, dropped = statelib.build(_dirs(args), root=getattr(args, "root", Path(".")), out=args.out,
                                  keep_legs=args.keep_legs, kb=_kb_json("rom_tables.json"))
    tiers = Counter(e["tier"] for e in doc["entries"])
    verdicts = Counter(e["verdict"] for e in doc["entries"])
    print(f"{len(doc['entries'])} states {dict(tiers)}; verdicts {dict(verdicts)}; "
          f"{len(dropped)} leg(s) retention would drop")
    for e in dropped:
        print(f"would drop {e['name']} ({e['state']})")
    return 0


def cmd_library_list(args) -> int:
    """``states library list``: one row per entry - tier, name, segment, build, verdict, readiness, steps, run."""
    for e in statelib.read(args.lib).get("entries", []):
        if args.tier and e["tier"] != args.tier or args.segment and e.get("segment") != args.segment \
                or args.build and e.get("build") != args.build or args.clean_only and e.get("verdict") != "clean":
            continue
        m = e.get("metrics") or {}
        print("\t".join(str(x) for x in (e["tier"], e["name"], e.get("segment"), e.get("build"), e.get("verdict"),
                                        m.get("readiness"), m.get("steps"), e.get("run"))))
    return 0


def cmd_library_validate(args) -> int:
    """``states library validate``: re-run the party rules on every entry's sidecar and print a RETIRABLE line
    (with the nearest clean ancestor) for each state that turns clean -> violation. Exit 1 when any checkpoint is
    retirable, or any state under ``--strict``. Report-only: nothing is moved, retired or deleted."""
    entries = statelib.read(args.lib).get("entries", [])
    root = Path(getattr(args, "root", "."))
    idx = {e["state"]: statefp.read(root / e["state"]) for e in entries}
    rep = statelib.revalidate(entries, _kb_json("rom_tables.json"), idx)
    for line in rep.lines:
        print(line)
    print(f"{len(rep.retirable)} retirable state(s)")
    return 1 if any(args.strict or e["tier"] == "checkpoint" for e in rep.retirable) else 0


def add_parser(sub) -> None:
    """``pokeagent states <sub> [--dir D ...]``; a repeatable --dir overrides the two default state dirs."""
    p = sub.add_parser("states", help="save-state ledger: list, check, restamp, retire, library")
    s = p.add_subparsers(dest="states_cmd", required=True)

    def dirs(sp):
        sp.add_argument("--dir", action="append", default=None, metavar="D",
                        help="state dir (repeatable; default runs/checkpoints and runs/legs/states)")

    lp = s.add_parser("list", help="one row per state: name, map, x,y, respawn, party, HP%%, money, source run, status")
    lp.add_argument("--map", type=lambda v: int(v, 0), default=None, metavar="M", help="only states on this map id")
    lp.add_argument("--bad", action="store_true", help="only states statelog.bad flags, with the reason")
    dirs(lp)
    lp.set_defaults(func=cmd_list)

    cp = s.add_parser("check", help="fail when a ship state respawns behind Vermilion, is unstamped/stale, or a checkpoint breaks a party rule")
    cp.add_argument("--legal", action="store_true", help="run the legality checker on every state (exit 1 on any violation)")
    cp.add_argument("--envelope", action="store_true", help="with --legal: also print the organic-envelope verdicts")
    cp.add_argument("--strict", action="store_true", help="fail on any party-rule violation and on unknown verdicts")
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

    lb = s.add_parser("library", help="the save library: index checkpoints and leg states by team build")
    ls = lb.add_subparsers(dest="library_cmd", required=True)

    bp = ls.add_parser("build", help="scan the state dirs and write runs/states/library.json")
    bp.add_argument("--out", type=Path, default=statelib.LIBRARY, metavar="PATH")
    bp.add_argument("--keep-legs", type=int, default=statelib.library.KEEP_LEGS, metavar="K")
    bp.add_argument("--root", type=Path, default=Path("."), metavar="R",
                    help="the repo root the index's state paths are relative to (runs/ lives under it)")
    dirs(bp)
    bp.set_defaults(func=cmd_library_build)

    ll = ls.add_parser("list", help="list library entries: tier, name, segment, build, verdict, readiness, steps, run")
    ll.add_argument("--lib", type=Path, default=statelib.LIBRARY, metavar="PATH")
    ll.add_argument("--tier", choices=("checkpoint", "leg"), default=None)
    ll.add_argument("--segment", default=None, metavar="S")
    ll.add_argument("--build", default=None, metavar="B")
    ll.add_argument("--clean-only", action="store_true", help="only verdict=clean entries")
    ll.set_defaults(func=cmd_library_list)

    vp = ls.add_parser("validate", help="re-run the party rules; print RETIRABLE lines with clean ancestors")
    vp.add_argument("--lib", type=Path, default=statelib.LIBRARY, metavar="PATH")
    vp.add_argument("--root", type=Path, default=Path("."), metavar="R")
    vp.add_argument("--strict", action="store_true", help="exit 1 when any state is retirable, not just checkpoints")
    vp.set_defaults(func=cmd_library_validate)
