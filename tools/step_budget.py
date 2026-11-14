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

from pokeagent.explorer.world import POKECENTER_MAPS

ROUTE24_MAP = 35                       # 0x23
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
EPISODE_RE = re.compile(r"\[grind episode\] start on (\S+)")
REORDER_GAP = 3   # reorder_party decisions <= this many steps apart are one session (training-controller plan, section 5)
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


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass  # a torn last line of a killed run
    return rows


def reorder_sessions(decisions: list[dict]) -> list[dict]:
    """Maximal runs of reorder_party decision lines with gaps <= REORDER_GAP steps: [{start, end, lines, map}]."""
    out: list[dict] = []
    for d in decisions:
        if not str(d.get("rule", "")).startswith("reorder_party"):
            continue
        if out and d["step"] - out[-1]["end"] <= REORDER_GAP:
            out[-1]["end"], out[-1]["lines"] = d["step"], out[-1]["lines"] + 1
        else:
            out.append({"start": d["step"], "end": d["step"], "lines": 1, "map": d.get("map")})
    return out


def episode_starts(console: Path) -> dict:
    """Grind-episode starts by the map name in the '[grind episode] start on NAME' log line."""
    c: Counter = Counter()
    with open(console, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = EPISODE_RE.search(line)
            if m:
                c[m.group(1).rstrip(":")] += 1
    return dict(c)


def floor_progress(levels: list[dict]) -> dict:
    """First step each party slot's level was seen at each level: {"slot:level": step} (a slot keeps its order, so the
    floor check is 'step at which two slots first reach the floor level')."""
    first: dict[str, int] = {}
    for r in levels:
        for slot, mon in enumerate(r.get("party") or []):
            first.setdefault(f"{slot}:{mon[1]}", r["step"])
    return first


def run_rows(run_dir: Path) -> dict:
    """Training-controller acceptance rows from the run dir's decisions/levels/xp_rates files (missing file -> empty row)."""
    sessions = reorder_sessions(_jsonl(run_dir / "decisions.jsonl"))
    levels = _jsonl(run_dir / "levels.jsonl")
    xp = {r["map"]: r.get("xp_per_1k_steps", 0.0) for r in _jsonl(run_dir / "xp_rates.jsonl") if r.get("kind") == "map_summary"}
    log = run_dir / "console.log"
    return {"reorder_sessions": len(sessions), "reorder_lines": sum(s["lines"] for s in sessions),
            "reorder_in_pokecenter": sum(1 for s in sessions if s["map"] in POKECENTER_MAPS),
            "episode_starts": episode_starts(log) if log.is_file() else {},
            "blackouts": max((r.get("blackouts", 0) for r in levels), default=0),
            "route24_xp_per_1k": xp.get(ROUTE24_MAP, 0.0), "floor_first_step": floor_progress(levels)}


def render(b: dict) -> str:
    n = max(1, b["steps"])
    rows = [f"steps: {b['steps']}", "", "| Activity | Lines | % of steps |", "|---|---|---|"]
    rows += [f"| {k} | {v} | {100 * v / n:.1f}% |" for k, v in b["activities"].items()]
    rows += ["", "| Map | Steps |", "|---|---|"] + [f"| {k} | {v} |" for k, v in b["maps"].items()]
    r = b.get("rows")
    if r:
        rows += ["", "| Training-controller row | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in r.items()]
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
    b["rows"] = run_rows(a.run_dir)
    print(json.dumps(b, indent=1) if a.json else render(b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
