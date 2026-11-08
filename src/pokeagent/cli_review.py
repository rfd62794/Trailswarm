"""``pokeagent review``: operator/overseer run, swarm, replay and diff tools.

Text by default, ``--json`` for machine use (sorted keys, stable for diffing). All logic lives in
``pokeagent.review``; this file is argparse + emit. Exit codes: 0 nothing broken, 1 breaks found,
2 usage/missing input. Tests call ``main(argv)`` / the handlers, never the entry point.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

from pokeagent.review import diff as review_diff
from pokeagent.review import load, render, replay, swarm, timeline


def _cmd_run(args) -> int:
    run_dir = load.resolve_run_dir(args.run, Path(args.runs_dir))
    if run_dir is None:
        return render.error(f"run not found: {args.run}", args.json)
    s = timeline.summarise(load.load_run(run_dir), max_events=args.max_events)
    render.emit(s, args.json, render.run_text(s))
    return 1 if s["breaks"] else 0


def _cmd_swarm(args) -> int:
    try:
        since = swarm.parse_since(args.since)
        until = swarm.parse_since(args.until) if args.until else None
    except ValueError as e:
        return render.error(f"bad --since/--until: {e}", args.json)
    s = swarm.summarise(Path(args.runs_dir), since, until,
                        segment=args.segment, top=args.top, invariants_verbose=args.invariants)
    render.emit(s, args.json, render.swarm_text(s))
    return 1 if s["broken"] else 0


def _cmd_diff(args) -> int:
    a = load.resolve_run_dir(args.a, Path(args.runs_dir))
    b = load.resolve_run_dir(args.b, Path(args.runs_dir))
    if a is None:
        return render.error(f"run not found: {args.a}", args.json)
    if b is None:
        return render.error(f"run not found: {args.b}", args.json)
    d = review_diff.diff(load.load_run(a), load.load_run(b))
    render.emit(d, args.json, render.diff_text(d))
    return 0


def _head_sha() -> str | None:
    """``git rev-parse HEAD`` - called ONLY here, never inside the pure replay functions."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        return out.stdout.strip() or None
    except OSError:
        return None


def _cmd_replay(args) -> int:
    run_dir = load.resolve_run_dir(args.run, Path(args.runs_dir))
    if run_dir is None:
        return render.error(f"run not found: {args.run}", args.json)
    rep = replay.run_replay(run_dir, args.steps, Path(args.runs_dir), head_sha=_head_sha())
    out = rep.to_json()
    render.emit(out, args.json, render.replay_text(out))
    return {"identical": 0, "diverged": 1}.get(rep.status, 2)


def _cmd_segments(args) -> int:
    root = Path(args.root)
    if not root.is_dir() or not (root / "runs").is_dir():
        return render.error(f"unreadable root: {root}", args.json)
    from pokeagent.review import segments as rseg
    try:
        s = rseg.summarise(root, suite=args.suite, do_ingest=not args.no_ingest)
    except ValueError as e:
        return render.error(str(e), args.json)
    render.emit(s, args.json, render.segments_text(s))
    return 1 if s["broken"] else 0


def _add_commands(rsub) -> None:
    """Attach every review subcommand to a subparsers object."""
    r = rsub.add_parser("run", help="compressed event timeline for one run")
    r.add_argument("run", metavar="RUN", help="run dir path or bare run name under --runs-dir")
    r.add_argument("--runs-dir", default="runs", metavar="DIR")
    r.add_argument("--json", action="store_true", help="machine output (default: text)")
    r.add_argument("--max-events", type=int, default=timeline.MAX_EVENTS, metavar="N")
    r.set_defaults(func=_cmd_run)

    s = rsub.add_parser("swarm", help="cross-run roll-up with a breaks section")
    s.add_argument("--since", required=True, metavar="TIME",
                   help="HH:MM (today), ISO, or Nm/Nh ago")
    s.add_argument("--until", default=None, metavar="TIME")
    s.add_argument("--runs-dir", default="runs", metavar="DIR")
    s.add_argument("--json", action="store_true")
    s.add_argument("--segment", default=None, metavar="NAME")
    s.add_argument("--top", type=int, default=5, metavar="N")
    s.add_argument("--invariants", action="store_true", help="list WARN findings too")
    s.set_defaults(func=_cmd_swarm)

    d = rsub.add_parser("diff", help="timeline diff of two runs")
    d.add_argument("a", metavar="RUN_A")
    d.add_argument("b", metavar="RUN_B")
    d.add_argument("--runs-dir", default="runs", metavar="DIR")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_cmd_diff)

    p = rsub.add_parser("replay", help="determinism check: re-run a run's start state for N steps")
    p.add_argument("run", metavar="RUN")
    p.add_argument("--steps", type=int, required=True, metavar="N")
    p.add_argument("--runs-dir", default="runs", metavar="DIR")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_replay)

    g = rsub.add_parser("segments", help="segment scorecard: grades, effective shares, rejoin candidates")
    g.add_argument("--root", default=".", metavar="DIR", help="checkout root holding runs/ (default: cwd)")
    g.add_argument("--suite", default=None, metavar="NAME", help="only this suite's segments (runs/segment_sets.json)")
    g.add_argument("--no-ingest", action="store_true", help="read runs/segments.json as it is; do not scan run folders")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=_cmd_segments)


def register(sub) -> None:
    """Attach the ``review`` subcommand tree to the main CLI's subparsers."""
    rp = sub.add_parser("review", help="operator run/swarm/replay/diff review tools (text, --json)")
    _add_commands(rp.add_subparsers(dest="review_command", required=True))


def main(argv: list[str] | None = None) -> int:
    """Standalone entry for tests: same commands, no 'review' prefix."""
    parser = argparse.ArgumentParser(prog="pokeagent review")
    _add_commands(parser.add_subparsers(dest="review_command", required=True))
    args = parser.parse_args(argv)
    return args.func(args)
