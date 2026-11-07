"""Check 2: impossible entries in milestones.json, via tools/milestones_clean.find_impossible."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from pokeagent.invariants.findings import ERROR, INFO, Finding, read_json

_TOOLS = Path(__file__).resolve().parents[3] / "tools"


def _clean_mod():
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    import milestones_clean
    return milestones_clean


def check_milestones(runs_dir: Path) -> list[Finding]:
    data, err = read_json(runs_dir / "milestones.json")
    if err or not isinstance(data, dict):
        return [Finding("milestones", ERROR if err else INFO, "unreadable", f"milestones.json: {err or 'missing or not an object'}")]
    bad, unjudged = _clean_mod().find_impossible(data, runs_dir)
    per_goal = Counter(g for g, _e, _w in bad)
    out = []
    for goal, n in sorted(per_goal.items(), key=lambda kv: -kv[1]):
        e, why = next((e, w) for g, e, w in bad if g == goal)
        out.append(Finding("milestones", ERROR, "impossible_milestone",
                           f"goal {goal}: {n} impossible entries (e.g. {e.get('run')} step {e.get('step')}: {why})",
                           {"goal": goal, "count": n}))
    if unjudged:
        out.append(Finding("milestones", INFO, "unjudged", f"{unjudged} entries have no run meta.json and were not judged"))
    return out
