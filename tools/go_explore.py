"""Go-Explore driver (plan slice 4): return to an archived cell, spend a bounded explore budget, repeat.

    uv run python tools/go_explore.py --archive runs/goexplore/<run-id> --start-state <organic .state> [--returns 3] [--steps 600] [--seed 0] [--stop-at-goal GOAL] [--dry-run]

Each return is one ``tools/explore_demo.py`` process (sequential, one emulator at a time, plan D6);
the Harvester attached by ``--cell-dump`` writes new cells back into the same archive. ``--dry-run``
prints the next return's command line without touching the archive or starting anything.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.goals import GOALS  # noqa: E402
from pokeagent.goexplore import runner  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", required=True, help="Go-Explore archive dir (runs/goexplore/<run-id>)")
    ap.add_argument("--start-state", required=True,
                    help="organic/promoted .state the first return starts from (empty archive)")
    ap.add_argument("--returns", type=int, default=3, help="number of return-and-explore runs")
    ap.add_argument("--steps", type=int, default=runner.DEFAULT_STEPS, help="emulator steps per return (plan D6)")
    ap.add_argument("--seed", type=int, default=0, help="base seed; return i uses seed + i (plan D1)")
    ap.add_argument("--stop-at-goal", default=None, choices=GOALS, help="end each run when this goal lands")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the next return's command only; touches no archive file, starts no process")
    a = ap.parse_args(argv)
    root, start = Path(a.archive), Path(a.start_state)
    try:
        if a.dry_run:
            r = runner.pick(root, start, index=0, base_seed=a.seed, commit=False)
            print(" ".join(runner.command(r, root, steps=a.steps, stop_goal=a.stop_at_goal)))
            return 0
        codes = runner.drive(root, start, a.returns, steps=a.steps, base_seed=a.seed,
                             stop_goal=a.stop_at_goal)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"go_explore: refused: {exc}", file=sys.stderr)
        return 2
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
