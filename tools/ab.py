"""One-command A/B of two explorer variants on the same seeds (headless, one emulator at a time).

    uv run python tools/ab.py --state runs/checkpoints/nugget_bridge.state --goal to_bill --seeds 1-4 --steps 3000 \
        --a "" --b "--bandit" [--a-ref REF] [--b-ref REF] [--label L] [--dry-run]
    uv run python tools/ab.py list

Variants differ by extra explore_headless flags (--a/--b, passed through verbatim) and/or git ref (--a-ref/--b-ref, run from a
temporary git worktree, removed afterwards; the live checkout is untouched). Runs execute in a scratch cwd so the explorer's
relative runs/ writes (checkpoints, milestones, bandit) never hit the live tree. One maps.json snapshot is shared by every run.
Results are appended to runs/ab_results.jsonl (override with --results).
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent.evaluation_ab import extract_metrics, summarize  # noqa: E402


def parse_seeds(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        lo, _, hi = part.partition("-")
        out += range(int(lo), int(hi or lo) + 1)
    return out


def build_cmd(root: Path, args, flags: str, seed: int, maps: str | None, starter: str | None = None) -> list[str]:
    cmd = [sys.executable, str(root / "tools" / "explore_headless.py"), "--rom", str(Path(args.rom).resolve()),
           "--state", str(Path(args.state).resolve()), "--steps", str(args.steps), "--seed", str(seed),
           "--stop-at-goal", args.goal]
    if maps:
        cmd += ["--maps-copy", maps]
    if starter:
        cmd += ["--starter", starter]
    return cmd + [t.strip('"') for t in shlex.split(flags, posix=False)]


def run_one(cmd: list[str], cwd: Path, goal: str, cap: int) -> dict:
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    try:
        work = json.loads(p.stdout[p.stdout.index("{"):])["work"]
    except (ValueError, KeyError):
        return {"solved": False, "steps": None, "frames": None, "presses": 0, "cap": cap, "stalls": 0, "blackouts": 0,
                "battles": 0, "item_tossed": 0, "error": (p.stderr or p.stdout)[-300:]}
    m = extract_metrics(work, goal, cap)
    m["secs"] = round(time.time() - t0, 1)
    shutil.rmtree(work, ignore_errors=True)
    return m


def fmt(v) -> str:
    return "-" if v is None else str(v)


def render(seeds, ra, rb, sm) -> str:
    keys = ("solved", "steps", "frames", "presses", "stalls", "blackouts", "battles", "item_tossed")
    head = " | ".join(f"{v} {k}" for v in "AB" for k in keys)
    rows = [f"| seed | {head} |", "|" + "---|" * (1 + 2 * len(keys))]
    for s, a, b in zip(seeds, ra, rb):
        rows.append(f"| {s} | " + " | ".join(fmt(x[k]) for x in (a, b) for k in keys) + " |")
    side = lambda n, s: f"{n}: solved {s['solved']}/{s['n']} ({s['solve_rate']:.0%}), median steps {fmt(s['median_steps'])}"  # noqa: E731
    extra = "" if sm["p_value"] is None else f", p={sm['p_value']:.3f}"
    return ("\n".join(rows) + f"\n\n{side('A', sm['a'])}\n{side('B', sm['b'])}\n"
            f"paired B-A steps (unsolved = cap): {sm['paired_diffs']}, mean {fmt(sm['mean_diff'])}, median {fmt(sm['median_diff'])}; "
            f"{sm['test']}{extra}")


def add_ref_worktree(ref: str, tmp: Path, tag: str) -> Path:
    wt = tmp / f"wt-{tag}"
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(wt), ref], check=True, capture_output=True)
    if (ROOT / "kb").exists():
        shutil.copytree(ROOT / "kb", wt / "kb", dirs_exist_ok=True)  # gitignored ROM-derived tables
    return wt


def cmd_list(path: Path) -> int:
    for ln in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []):
        r = json.loads(ln)
        sm = r["summary"]
        print(f"{r['ts']}  {r['label'] or '-'}  {Path(r['state']).stem}->{r['goal']}  seeds {r['seeds']}  "
              f"A[{r['a_flags']!r} {r['a_ref'] or 'live'}] {sm['a']['solved']}/{sm['a']['n']} med {fmt(sm['a']['median_steps'])}  "
              f"B[{r['b_flags']!r} {r['b_ref'] or 'live'}] {sm['b']['solved']}/{sm['b']['n']} med {fmt(sm['b']['median_steps'])}  {sm['test']}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for i, tok in enumerate(argv[:-1]):  # `--b "--bandit"`: argparse would read the value as an option, so glue it to its flag
        if tok in ("--a", "--b") and argv[i + 1].startswith("-"):
            argv[i], argv[i + 1] = f"{tok}={argv[i + 1]}", None
    argv = [t for t in argv if t is not None]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state"); ap.add_argument("--goal")
    ap.add_argument("--seeds", default="1-4"); ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--a", default="", help="extra explore_headless flags for A (one quoted string)")
    ap.add_argument("--b", default="", help="extra explore_headless flags for B")
    ap.add_argument("--a-ref"); ap.add_argument("--b-ref"); ap.add_argument("--label", default="")
    ap.add_argument("--rom", default=str(ROOT / "roms" / "Pokemon Red.gb"))
    ap.add_argument("--maps", default=str(ROOT / "runs" / "maps.json"), help="map memory to snapshot once (missing: fresh)")
    ap.add_argument("--results", default=str(ROOT / "runs" / "ab_results.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--suite", default=None, metavar="NAME",
                    help="one A/B per member of this suite (runs/segment_sets.json; --state/--goal come from each segment)")
    ap.add_argument("cmd", nargs="?", choices=["list"])
    args = ap.parse_args(argv)
    results = Path(args.results)
    if args.cmd == "list":
        rc = cmd_list(results)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import seg_suites  # noqa: E402
        print("suites: " + ", ".join(sorted(seg_suites.load_suites(ROOT))))
        return rc
    if args.suite:
        members = _suite_members(ROOT, args.suite)
        if members is None:
            ap.error(f"unknown or malformed suite {args.suite!r}")
        if not members:
            ap.error(f"suite {args.suite!r} resolved to no runnable members")
        rc = 0
        for seg, start, starter in members:
            print(f"--- suite {args.suite}: {seg.key}" + (f" (starter {starter})" if starter else ""))
            margs = argparse.Namespace(**{**vars(args), "state": start, "goal": seg.stop_goal,
                                          "label": f"{args.label or args.suite}:{seg.key}"})
            rc |= _run_ab(margs, starter)
        return rc
    if not (args.state and args.goal):
        ap.error("--state and --goal are required (or --suite NAME)")
    return _run_ab(args)


def _run_ab(args, starter: str | None = None) -> int:
    results = Path(args.results)
    seeds = parse_seeds(args.seeds)
    tmp = Path(tempfile.mkdtemp(prefix="ab-"))
    maps = str(tmp / "maps_snapshot.json") if Path(args.maps).exists() else None  # ONE snapshot: identical map memory for A and B
    plan = [(v, seed) for seed in seeds for v in "ab"]
    if args.dry_run:
        for v, seed in plan:
            ref = getattr(args, f"{v}_ref")
            print(f"[{v.upper()} seed {seed}] cwd={tmp / 'cwd'} " + " ".join(build_cmd(Path(f"<worktree@{ref}>") if ref else ROOT, args, getattr(args, v), seed, maps, starter)))
        shutil.rmtree(tmp, ignore_errors=True)
        return 0
    if maps:
        shutil.copy(args.maps, maps)
    roots, res = {"a": ROOT, "b": ROOT}, {"a": [], "b": []}
    try:
        for v in "ab":
            if getattr(args, f"{v}_ref"):
                roots[v] = add_ref_worktree(getattr(args, f"{v}_ref"), tmp, v)
        scratch = tmp / "cwd"
        scratch.mkdir()
        for v, seed in plan:  # sequential: one emulator at a time
            m = run_one(build_cmd(roots[v], args, getattr(args, v), seed, maps, starter), scratch, args.goal, args.steps)
            res[v].append(m)
            print(f"[{v.upper()} seed {seed}] solved={m['solved']} steps={m['steps']} presses={m['presses']} {m.get('error', '')}", flush=True)
    finally:
        for r in {roots["a"], roots["b"]} - {ROOT}:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(r)], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    sm = summarize(res["a"], res["b"], args.steps)
    print("\n" + render(seeds, res["a"], res["b"], sm))
    results.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": args.label, "a_ref": args.a_ref, "b_ref": args.b_ref,
           "a_flags": args.a, "b_flags": args.b, "state": args.state, "goal": args.goal, "seeds": seeds, "steps": args.steps,
           "runs": res, "summary": sm}
    with results.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return 0


def _suite_members(root: Path, name: str):
    """Resolve a suite through seg_suites to (segment, starter) pairs the per-goal flow can run."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import seg_store as ss  # noqa: E402
    import seg_suites      # noqa: E402
    from pokeagent import segment_grades as sg  # noqa: E402
    doc = ss.load(root)
    members = seg_suites.resolve(name, doc, sg.grade_all(doc, root, time.time()), root)
    if members is None:
        return None
    out = []
    for m in members:
        seg = next((s for s in ss.layout(doc) if s.key == m["key"]), None)
        if seg is None or not seg.stop_goal:
            print(f"suite {name}: {m['key']} has no goal stop (map-stop sub-segment), skipped")
            continue
        start = ss.ckpt(root, seg.start)
        if start is None:
            print(f"suite {name}: {m['key']}: no start checkpoint for {seg.start}, skipped")
            continue
        out.append((seg, str(start), m.get("starter")))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
