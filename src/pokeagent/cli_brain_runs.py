"""``brain compare`` / ``brain assists`` / ``brain seed``: cross-file reports and memory seeding.

Argparse and emit only, attached to ``pokeagent brain`` by one call in
``cli_brain._add_commands``; all logic lives in ``pokeagent.brain`` (compare.py, assists.py,
seed.py). Imported lazily by cli_brain so this module can reuse its ``_emit``/``_err`` helpers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pokeagent.brain as brain
from pokeagent.brain import fileops
from pokeagent.cli_brain import _emit, _err
from pokeagent.goals import GOALS
from pokeagent.review.load import jsonl, load_json


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.1%}" if den else "n/a"


def _load_maps_file(path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"maps file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _compare_text(out: dict) -> str:
    t, w, n, wa = (out["totals"][k] for k in ("tiles", "warps", "npcs", "walls"))
    lines = [f"shared maps: {out['shared_maps']}",
             f"tiles: {t['overlap']}/{t['candidate']} in baseline ({_ratio(t['overlap'], t['candidate'])}); "
             f"{t['candidate_only']} candidate-only",
             f"warps: {w['common']} common, {w['different']} different, {w['candidate_only']} candidate-only",
             f"npcs: {n['overlap']}/{n['candidate']} stationary NPCs match ({_ratio(n['overlap'], n['candidate'])})",
             f"walls: {wa['suspect']}/{wa['baseline_walls']} baseline walls suspect "
             f"({_ratio(wa['suspect'], wa['baseline_walls'])}): ledge_exact={wa['ledge_exact']} "
             f"ledge_row={wa['ledge_row']} (heuristic) unexplained={wa['unexplained']} "
             f"malformed={wa['malformed']}"]
    for r in out["rows"]:
        lines.append(f"  map {r['map']}: unexplained={r['walls']['unexplained']} "
                     f"candidate_only={r['tiles']['candidate_only']}")
    return "\n".join(lines)


def _assists_text(out: dict) -> str:
    lines = [f"presses: {out['total_presses']} total, {out['assist_presses']} assists "
             f"by_source={out['by_source']}"]
    for c in out["clusters"]:
        lines.append(f"  cluster map={c['map']} steps {c['step_start']}-{c['step_end']} "
                     f"presses={c['presses']} stage={c['goal_stage']} by_source={c['by_source']} "
                     f"buttons={c['buttons']}")
    for g in out["goal_ends"]:
        detail = "unaided" if g["unaided"] else f"{g['assists_in_stage']} assist press(es) in stage"
        lines.append(f"  goal {g['goal']} at step {g['step']}: {detail}")
    lines.append(f"final_stage={out['final_stage']} milestone_unaided={out['milestone_unaided']}")
    return "\n".join(lines)


def _seed_text(out: dict) -> str:
    r, ps = out["removed"], out["removed"]["playthrough_state"]
    return (f"seeded: maps={out['maps']} top_level_keys_kept={out['top_level_keys_kept']} "
            f"removed: encounters={r['encounters']} loops={r['loops']} demos={r['demos']} "
            f"interaction_done={ps['interaction_done']} npc_results_done={ps['npc_results_done']}")


def _cmd_compare(args) -> int:
    try:
        a, b = _load_maps_file(args.a), _load_maps_file(args.b)
    except (OSError, ValueError) as e:
        return _err(args, str(e))
    out = brain.compare_memory(a, b)
    _emit(out, args, _compare_text(out))
    return 0


def _cmd_assists(args) -> int:
    run_dir = Path(args.run_dir)
    tpath = run_dir / "transitions.jsonl"
    if not tpath.is_file():
        return _err(args, f"transitions.jsonl not found in {run_dir}")
    initial = load_json(run_dir / "meta.json").get("initial_goals") or []
    out = brain.assists_report(jsonl(tpath), jsonl(run_dir / "goal_frames.jsonl"),
                               initial if isinstance(initial, list) else [], GOALS, gap=args.gap)
    _emit(out, args, _assists_text(out))
    return 0


def _cmd_seed(args) -> int:
    src, dst = Path(args.src), Path(args.dst)
    if not src.is_file():
        return _err(args, f"source maps file not found: {src}")
    if src.resolve() == dst.resolve():
        return _err(args, "destination equals source - refusing to seed in place")
    if dst.exists():
        return _err(args, f"destination already exists: {dst}")
    seeded, removed = brain.seed_memory(
        fileops.effective_data(src)[0], no_encounters=args.no_encounters, no_loops=args.no_loops,
        no_demos=args.no_demos, no_playthrough_state=args.no_playthrough_state)
    out = {"maps": len(seeded.get("maps") or {}), "removed": removed,
           "top_level_keys_kept": len(seeded)}
    try:
        dst.write_text(json.dumps(seeded, indent=1), encoding="utf-8")
    except OSError as e:
        return _err(args, str(e))
    _emit(out, args, _seed_text(out))
    return 0


def add_commands(bsub) -> None:
    """Attach the compare/assists/seed subcommands to the brain subparsers."""
    c = bsub.add_parser("compare", help="compare two maps.json memories (baseline A vs candidate B)")
    c.add_argument("a", metavar="A.json")
    c.add_argument("b", metavar="B.json")
    c.add_argument("--text", action="store_true")
    c.set_defaults(func=_cmd_compare)

    a = bsub.add_parser("assists", help="how much human/claude help one run dir got")
    a.add_argument("run_dir", metavar="RUN_DIR")
    a.add_argument("--gap", type=int, default=20, help="max step gap inside one assist cluster")
    a.add_argument("--text", action="store_true")
    a.set_defaults(func=_cmd_assists)

    s = bsub.add_parser("seed", help="copy a maps.json, optionally stripping run-specific state")
    s.add_argument("src", metavar="SRC.json")
    s.add_argument("dst", metavar="DST.json")
    s.add_argument("--no-encounters", action="store_true", help="drop per-map wild encounter tables")
    s.add_argument("--no-loops", action="store_true", help="drop the shared dead-move table")
    s.add_argument("--no-demos", action="store_true", help="drop per-map recorded demos")
    s.add_argument("--no-playthrough-state", action="store_true",
                   help="clear 'done' flags on interaction entries and NPC results")
    s.add_argument("--text", action="store_true")
    s.set_defaults(func=_cmd_seed)
