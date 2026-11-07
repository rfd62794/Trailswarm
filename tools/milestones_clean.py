"""One-off: list (and optionally drop) impossible entries in runs/milestones.json.

milestones.json maps goal -> [{"run", "step", ...}], the first time each run reached the goal. Two kinds of entry are impossible:
  predecessor  the goal's ``after`` predecessor (nearest verified one) was neither reached earlier in the same run nor already
               done at its start (meta.json ``initial_goals``);
  far-start    the run started more than --far goals before this one and some verified goal in between was never reached.
Goals before --from-goal (default to_route3) are not judged. Entries from runs whose meta.json is missing are kept (nothing to judge them by) and counted.

    uv run python tools/milestones_clean.py                     # report only
    uv run python tools/milestones_clean.py --apply             # also write runs/milestones.cleaned.json (a COPY)

The live swarm writes runs/milestones.json, so this never writes to it: the output path may not be the input path.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent import campaign  # noqa: E402


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_facts(runs_dir: Path, run: str):
    """(start_index, initial goal set, {goal: step reached in this run}) or None when the run has no meta.json."""
    meta = _load(runs_dir / run / "meta.json")
    if not isinstance(meta, dict):
        return None
    order = campaign.goal_ids()
    initial = set(meta.get("initial_goals") or [])
    start_name = str(meta.get("start") or "").split("@", 1)[0]
    idx = [order.index(g) for g in initial | {start_name} if g in order]
    reached: dict[str, int] = {}
    try:
        for line in (runs_dir / run / "goal_frames.jsonl").read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            reached.setdefault(rec["goal"], int(rec["step"]))
    except (OSError, ValueError, KeyError):
        pass
    return (max(idx) if idx else 0), initial, reached


def verified_predecessor(goal: str):
    """Nearest earlier goal that has a detector of its own (unverified goals are never recorded)."""
    spec = campaign.goal_spec(goal)
    while spec and spec.get("after"):
        prev = campaign.goal_spec(spec["after"])
        if prev is None or prev["detector"] != campaign.UNVERIFIED:
            return prev["id"] if prev else None
        spec = prev
    return None


def find_impossible(milestones: dict, runs_dir: Path, far: int = 4, from_goal: str = "to_route3"):
    """[(goal, entry, reason)] plus the count of entries that could not be judged (no meta.json)."""
    order = campaign.goal_ids()
    first = order.index(from_goal) if from_goal in order else 0
    facts: dict[str, object] = {}
    bad, unjudged = [], 0
    for goal, entries in milestones.items():
        if goal not in order:
            continue
        gi = order.index(goal)
        if gi < first:
            continue
        pred = verified_predecessor(goal)
        for e in entries:
            run = e.get("run", "")
            f = facts.setdefault(run, run_facts(runs_dir, run))
            if f is None:
                unjudged += 1
                continue
            start, initial, reached = f
            step = int(e.get("step", 0))
            done_before = lambda g: g in initial or (g in reached and reached[g] <= step) or any(  # noqa: E731
                x.get("run") == run and int(x.get("step", 0)) <= step for x in milestones.get(g, ()))
            if pred and not done_before(pred):
                bad.append((goal, e, f"predecessor {pred} not reached before it in this run"))
            elif gi - start > far:
                gaps = [g for g in order[start + 1:gi] if campaign.goal_spec(g)["detector"] != campaign.UNVERIFIED and not done_before(g)]
                if gaps:
                    bad.append((goal, e, f"run started at index {start} ({order[start]}), {gi - start} goals back; never reached {gaps[0]}"))
    return bad, unjudged


def cleaned(milestones: dict, bad) -> dict:
    drop = {(g, e.get("run"), e.get("step")) for g, e, _ in bad}
    out = {}
    for goal, entries in milestones.items():
        kept = [e for e in entries if (goal, e.get("run"), e.get("step")) not in drop]
        if kept:
            out[goal] = kept
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=Path, default=ROOT / "runs", help="runs directory (default: <repo>/runs)")
    ap.add_argument("--milestones", type=Path, default=None, help="input file (default: <runs>/milestones.json)")
    ap.add_argument("--far", type=int, default=4, help="goals a run may start behind a goal it reaches (default 4)")
    ap.add_argument("--from-goal", default="to_route3", help="only judge this goal and later: the opening goals (potion, "
                    "left_house, ...) are order-independent and older runs never logged them (default to_route3)")
    ap.add_argument("--apply", action="store_true", help="write the cleaned COPY (never the input)")
    ap.add_argument("--out", type=Path, default=None, help="copy path (default: <runs>/milestones.cleaned.json)")
    a = ap.parse_args(argv)
    src = a.milestones or a.runs / "milestones.json"
    data = _load(src)
    if not isinstance(data, dict):
        print(f"cannot read {src}", file=sys.stderr)
        return 2
    bad, unjudged = find_impossible(data, a.runs, a.far, a.from_goal)
    total = sum(len(v) for v in data.values())
    print(f"{src}: {total} entries, {len(bad)} impossible, {unjudged} not judged (no meta.json)")
    for goal, e, why in sorted(bad, key=lambda b: (campaign.goal_ids().index(b[0]), str(b[1].get("run")))):
        print(f"  {goal:20s} {e.get('run')} step {e.get('step')}: {why}")
    if a.apply:
        out = a.out or a.runs / "milestones.cleaned.json"
        if out.resolve() == src.resolve():
            print("refusing to overwrite the input", file=sys.stderr)
            return 2
        out.write_text(json.dumps(cleaned(data, bad), indent=1), encoding="utf-8")
        print(f"wrote {out} ({total - len(bad)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
