"""Distinct cells visited per run, counted offline from run-log decisions.jsonl (Go-Explore D2, slice 1).

    uv run python tools/cell_census.py RUN_DIR [RUN_DIR ...] [--json]

The log census measures (map, x // 4, y // 4, goals_reached_count) only: flag popcount and party
level live in RAM, so they are reported as not_in_logs until slice 3 measures them live.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pokeagent.goexplore.census import census

NOT_IN_LOGS_LINE = "flag_popcount and party_level_bucket: not in logs (measure live, slice 3)"


def render(c: dict) -> str:
    out = [f"cells: {c['cells']}  (runs: {c['runs']}, rows: {c['rows']}, skipped_rows: {c['skipped_rows']})",
           "", "| Run | Cells |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in c["cells_per_run"].items()]
    out += ["", "| Goals reached | Cells |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in c["cells_by_goals"].items()]
    out += ["", "| Block edge | Cells |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in c["block_sweep"].items()]
    out += ["", f"monotone violations: {json.dumps(c['monotone_violations'])}",
            f"out-of-order goals: {json.dumps(c['out_of_order_goals'])}"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dirs", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    dirs = []
    for d in a.run_dirs:
        if d.is_dir():
            dirs.append(d)
        else:
            print(f"not found: {d}", file=sys.stderr)
    if not dirs:
        return 2
    c = census(dirs)
    if a.json:
        print(json.dumps(c, indent=1))
    else:
        print(render(c))
        print(NOT_IN_LOGS_LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
