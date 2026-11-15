"""``pokeagent rewind``: play a finished run back as frames, activity segments and moments.

Pure playback over the run's own transitions/decisions/levels logs: it never opens a window and
never needs the ROM. Text by default, ``--json`` for machine use. Exit codes: 0 ok, 2 unknown run.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from pokeagent.review.load import load_run, resolve_run_dir
from pokeagent.rewind.frames import Rewind
from pokeagent.rewind.moments import moments
from pokeagent.rewind.segments import segments, shares


def _cmd_rewind(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.run, Path(args.runs))
    if run_dir is None:
        print(f"error: run not found: {args.run}", file=sys.stderr)
        return 2
    data = load_run(run_dir)
    rw = Rewind.from_run(data)
    segs, mts = segments(rw), moments(rw, data)
    steps = {"first": rw.first_step, "last": rw.last_step, "count": len(rw)}
    act, kinds = shares(segs), dict(sorted(Counter(m.kind for m in mts).items()))
    if args.json:
        out = {"run": data.name, "steps": steps, "activity": act, "moment_counts": kinds}
        if args.at is not None:
            out["frame"] = asdict(rw.frame(args.at))
        if args.segments:
            out["segments"] = [asdict(s) for s in segs]
        if args.moments:
            out["moments"] = [asdict(m) for m in mts]
        print(json.dumps(out, sort_keys=True))
        return 0
    print(f"run {data.name}: steps {steps['first']}-{steps['last']} ({steps['count']} steps)")
    print("activity: " + (", ".join(f"{a} {v:.0%}" for a, v in
                                 sorted(act.items(), key=lambda kv: -kv[1])) or "-"))
    print("moments: " + (", ".join(f"{k} x{n}" for k, n in kinds.items()) or "-"))
    if args.at is not None:
        f = rw.frame(args.at)
        print(f"frame {f.step}: map {f.map} ({f.x},{f.y}) facing {f.facing} "
              f"button {f.button or '-'} moved {f.moved} behaviour {f.behaviour or '-'} "
              f"rule {f.rule or '-'} outcome {f.outcome or '-'} goal {f.goal_stage or '-'} "
              f"battle_turn {f.battle_turn} textbox {f.textbox or '-'} source {f.source or '-'}")
        print("  party: " + (" ".join(f"{p.species}L{p.level} {p.hp}/{p.max_hp}"
                                    for p in f.party) or "-"))
    for s in segs if args.segments else ():
        print(f"{s.start}-{s.end} {s.activity} ({s.end - s.start + 1} steps)")
    for m in mts if args.moments else ():
        print(f"{m.step} {m.kind} {m.label}".rstrip())
    return 0


def add_parser(sub) -> None:
    """Attach the ``rewind`` subcommand to the main CLI's subparsers."""
    p = sub.add_parser("rewind", help="play a finished run back: frames, activity segments, moments")
    p.add_argument("run", metavar="RUN", help="run dir path or bare run name under --runs")
    p.add_argument("--runs", default="runs", metavar="DIR", help="runs directory (default: runs)")
    p.add_argument("--at", type=int, default=None, metavar="STEP", help="print the frame at STEP")
    p.add_argument("--segments", action="store_true", help="list the activity segments")
    p.add_argument("--moments", action="store_true", help="list the moments")
    p.add_argument("--json", action="store_true", help="machine output (default: text)")
    p.set_defaults(func=_cmd_rewind)
