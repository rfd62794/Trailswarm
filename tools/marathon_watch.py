"""Marathon watch: stall detector for single long runs (tag-prefixed explore-* run dirs).

    uv run python tools/marathon_watch.py --tag marathon- [--runs-dir runs] [--run DIR]
                                          [--once] [--interval 60] [--stop] [--port N]

One JSON line per check per run on stdout:
    {"t","run","tag","step","status":"ok|stalled|held|young","reason","detail","bundle"}
Without --once it loops every --interval seconds until Ctrl+C. Exit code is always 0 (the overseer
reads the lines). It only reads run dirs; the only side effects are the runs/stalls/ bundle and -
on a stalled run - a save_state POST (once per stall episode) and, with --stop, a stop POST.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import swarm_watch  # noqa: E402
from pokeagent.marathon import actions, bundle, rules  # noqa: E402
from pokeagent.marathon.reader import RunView, find_runs  # noqa: E402


def _hung_check(run_dir: Path):
    """ProgressWatch bound to this run dir (run_dir preset: no seed lookup). Only its hung branch
    is used - marathon rules replace its loop rule, which marathon XP/tile trickles defeat."""
    w = swarm_watch.ProgressWatch(run_dir.parent.parent, seed=0, since_wall=0.0)
    w.run_dir = run_dir
    return w.check


def check(view: RunView, hung_check, args, th) -> dict:
    view.refresh()
    try:
        verdict = rules.evaluate(view, th=th, hung_check=hung_check)
    except Exception as e:  # a run that cannot be judged must not kill the watch loop
        verdict = {"status": "ok", "reason": f"check error: {e!r}", "detail": "", "hits": []}
    line = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": view.name,
            "tag": view.meta.get("tag"), "step": view.presses, "status": verdict["status"],
            "reason": verdict["reason"], "detail": verdict["detail"], "bundle": None}
    if verdict["status"] == "stalled":
        path, created = bundle.write(view, verdict["reason"], verdict["hits"])
        line["bundle"] = str(path) if path else None
        port, token = actions.endpoint(view, args.port)
        if created:  # once per stall episode: a save state for the post-mortem
            line.update(actions.save_state(port, view.presses, token))
        if args.stop:
            line.update(actions.stop(port, token))
    print(json.dumps(line), flush=True)
    return line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="marathon_watch", description=__doc__.splitlines()[0])
    ap.add_argument("--tag", default="", help="meta.json tag prefix selecting runs (default: all explore-*)")
    ap.add_argument("--runs-dir", default="runs", help="parent dir of the run dirs (default: runs)")
    ap.add_argument("--run", type=Path, default=None, help="check this one run dir instead of scanning")
    ap.add_argument("--once", action="store_true", help="one check per run, then exit")
    ap.add_argument("--interval", type=float, default=60, help="seconds between checks (default: 60)")
    ap.add_argument("--stop", action="store_true",
                    help="ask a stalled run for a clean stop (default: report only)")
    ap.add_argument("--port", type=int, default=None, help="control API port override for save/stop")
    ap.add_argument("--goal-budget", type=int, default=rules.GOAL_BUDGET,
                    help="presses without a goal before a normal stage flags (default: %(default)s)")
    ap.add_argument("--grind-budget", type=int, default=rules.GRIND_BUDGET,
                    help="same while a floor-training stage is pending (default: %(default)s)")
    ap.add_argument("--dwell", type=int, default=rules.DWELL_PRESSES,
                    help="presses on one map before map_dwell flags (default: %(default)s)")
    ap.add_argument("--osc-transitions", type=int, default=rules.OSC_TRANSITIONS,
                    help="map-pair crossings in the window before oscillation flags (default: %(default)s)")
    ap.add_argument("--stall-escalations", type=int, default=rules.STALL_ESCALATIONS,
                    help="STALL escalations since the last goal before guard_stall flags (default: %(default)s)")
    args = ap.parse_args(argv)
    th = rules.Thresholds(goal_budget=args.goal_budget, grind_budget=args.grind_budget,
                          dwell=args.dwell, osc_transitions=args.osc_transitions,
                          stall_escalations=args.stall_escalations)
    runs_dir = Path(args.runs_dir)
    watches: dict[Path, tuple] = {}

    def watch(d: Path) -> tuple:
        if d not in watches:  # the ProgressWatch is per-run: it must see the file stop growing
            watches[d] = (RunView(d), _hung_check(d))
        return watches[d]

    try:
        while True:
            dirs = [args.run] if args.run else find_runs(runs_dir, args.tag)
            for d in dirs:
                view, hung = watch(d)
                check(view, hung, args, th)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
