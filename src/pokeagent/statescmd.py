"""``pokeagent states``: the save-state ledger CLI - ``list``, ``check``, ``restamp``, ``retire``.

Handlers take parsed args and return an exit code so tests call them without a process. The ledger is
``pokeagent.statelog`` (pure JSON over the ``.fp.json`` sidecars); ``restamp`` delegates to ``tools/stamp_states.py``
and needs the ROM unless ``--dry-run``.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pokeagent import checkpoint_goals as cg
from pokeagent import statefp, statelog

DEFAULT_DIRS = (Path("runs/checkpoints"), Path("runs/legs/states"))
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"


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
        hp = f"{statefp.party_hp_fraction(fp):.0%}" if fp.get("party") else "?"
        row = [e.path.name, g("map"), pos, g("respawn"), _party(fp) or "?", hp, g("money"), g("source_run"), statelog.status(e)]
        if args.bad:
            row.append(reason or "")
        print("\t".join(row))
    return 0


def cmd_check(args) -> int:
    """Exit 1 when a ship state (ship-goal stem, or a fingerprint on a ship map) respawns behind Vermilion or has a
    missing/stale sidecar; other bad states are listed but do not fail."""
    from pokeagent.explorer.world import SHIP_MAPS
    fail, rows = False, []
    for e in _entries(_dirs(args)):
        reason = statelog.bad(e)
        ship = e.stem in cg.SHIP_GOALS or e.fp.get("map") in SHIP_MAPS
        if ship and (e.fp.get("respawn") in cg.BEHIND_VERMILION or statelog.status(e) != "fresh"):
            fail = True
            reason = reason or "ship state with respawn behind Vermilion or a missing/stale sidecar"
        if reason:
            rows.append(f"{e.path.name}\t{statelog.status(e)}\t{reason}")
    for r in rows:
        print(r)
    print(f"{len(rows)} bad state(s)" if rows else "no bad states")
    return 1 if fail else 0


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

    lp = s.add_parser("list", help="one row per state: name, map, x,y, respawn, party, HP%, money, source run, status")
    lp.add_argument("--map", type=lambda v: int(v, 0), default=None, metavar="M", help="only states on this map id")
    lp.add_argument("--bad", action="store_true", help="only states statelog.bad flags, with the reason")
    dirs(lp)
    lp.set_defaults(func=cmd_list)

    cp = s.add_parser("check", help="fail when a ship state respawns behind Vermilion or is unstamped/stale")
    dirs(cp)
    cp.set_defaults(func=cmd_check)

    rp = s.add_parser("restamp", help="re-run tools/stamp_states.py on the state dirs (needs the ROM unless --dry-run)")
    rp.add_argument("--force", action="store_true", help="re-stamp states that already have a sidecar")
    rp.add_argument("--dry-run", action="store_true", help="list what would be stamped")
    dirs(rp)
    rp.set_defaults(func=cmd_restamp)

    tp = s.add_parser("retire", help="move a state and its sidecars into runs/retired with a reason")
    tp.add_argument("path", type=Path, metavar="PATH")
    tp.add_argument("--why", required=True, metavar="TEXT")
    tp.set_defaults(func=cmd_retire)
