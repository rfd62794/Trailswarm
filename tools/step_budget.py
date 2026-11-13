"""Where did the steps go? Count a run's `thinking:` lines by activity, and steps per map, from its console.log.

    uv run python tools/step_budget.py RUN_DIR            # table
    uv run python tools/step_budget.py RUN_DIR --json

Reproduces the Training v2 activity table (docs/plans/Training_V2.md). A thinking line can match several rows
(the rows are not exclusive); steps per map come from the `--- step N/M map=0x..` header lines.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ACTIVITIES = [   # (label, regex on the text after "thinking: ")
    ("BATTLE ... FIGHT", r"BATTLE.*FIGHT"),
    ("walking to grass (goal team_ready)", r"goal team_ready: \d+ steps to .* grass"),
    ("to the Pokecenter to heal", r"to the Pokecenter to heal"),
    ("leaving the Pokecenter", r"leaving the Pokecenter"),
    ("SHAKE random walk", r"SHAKE"),
    ("shake: closing a box", r"shake: closing a box"),
    ("closing the box with B", r"closing the box with B"),
    ("a text box is open", r"a text box is open"),
    ("busy: A in case text is waiting", r"busy: A in case text is waiting"),
]
STEP_RE = re.compile(r"^--- step (\d+)/\d+\s+map=0x([0-9a-fA-F]+)")


def budget(path: Path) -> dict:
    acts: Counter = Counter()
    maps: Counter = Counter()
    steps = 0
    compiled = [(n, re.compile(r)) for n, r in ACTIVITIES]
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = STEP_RE.match(line)
            if m:
                steps += 1
                maps[f"0x{int(m.group(2), 16):02X}"] += 1
            elif line.startswith("thinking:"):
                text = line[len("thinking:"):].strip()
                for name, rx in compiled:
                    if rx.search(text):
                        acts[name] += 1
    return {"steps": steps, "activities": {n: acts.get(n, 0) for n, _ in ACTIVITIES}, "maps": dict(maps.most_common())}


def render(b: dict) -> str:
    n = max(1, b["steps"])
    rows = [f"steps: {b['steps']}", "", "| Activity | Lines | % of steps |", "|---|---|---|"]
    rows += [f"| {k} | {v} | {100 * v / n:.1f}% |" for k, v in b["activities"].items()]
    rows += ["", "| Map | Steps |", "|---|---|"] + [f"| {k} | {v} |" for k, v in b["maps"].items()]
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    log = a.run_dir / "console.log"
    if not log.is_file():
        print(f"no console.log in {a.run_dir}", file=sys.stderr)
        return 2
    b = budget(log)
    print(json.dumps(b, indent=1) if a.json else render(b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
