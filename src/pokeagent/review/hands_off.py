"""Hands-off judge: did the agent alone reach a goal within a step budget?

Reads one run dir (``transitions.jsonl``, ``goal_frames.jsonl``, ``meta.json``) and returns a
``Verdict``. Every failing reason is collected; a bad or missing run dir never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pokeagent.review.load import jsonl, load_json, reached_rows


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: list[str]        # empty when passed; one short sentence per failure
    goal_step: int | None     # step of the goal line, None if absent
    presses: int              # rows in transitions.jsonl
    non_agent: int            # rows whose source is not "agent"


def _press_reasons(rows: list[dict], corrupt: int) -> tuple[list[str], int]:
    reasons: list[str] = []
    if not rows:
        reasons.append("transitions.jsonl missing or empty")
    if corrupt:
        reasons.append(f"{corrupt} corrupt transitions.jsonl line(s); zero human presses cannot be proven")
    bad = [r for r in rows if r.get("source") != "agent"]
    if bad:
        sources: list[str] = []
        for r in bad:
            s = str(r.get("source", "missing"))
            if s not in sources:
                sources.append(s)
        steps = ", ".join(str(r.get("step", "?")) for r in bad[:5])
        reasons.append(f"{len(bad)} non-agent presses ({', '.join(sources)}) at steps {steps}")
    return reasons, len(bad)


def _goal_reasons(run_dir: Path, goal: str, budget: int) -> tuple[list[str], int | None]:
    path = run_dir / "goal_frames.jsonl"
    rows = jsonl(path)
    row = next((r for r in reached_rows(rows) if r.get("goal") == goal), None)
    if row is None:
        if any(r.get("goal") == goal and r.get("skipped") for r in rows):
            return [f"goal {goal} was skipped (not reached)"], None
        initial = load_json(run_dir / "meta.json").get("initial_goals") or []
        if isinstance(initial, list) and goal in initial:
            return [f"goal {goal} was already true at the start state (initial_goals)"], None
        if not path.is_file():
            return ["goal_frames.jsonl missing"], None
        return [f"goal {goal} never reached"], None
    step = row.get("step")
    if not isinstance(step, int) or isinstance(step, bool):
        return ["goal row has no integer step"], None
    if step > budget:
        return [f"too slow: {goal} at step {step}, budget {budget}"], step
    return [], step


def normalize_goal(goal: str) -> str:
    """``map:0x25`` / ``map:37`` -> the ``map:0x25`` form the demo writes to goal_frames.jsonl."""
    if goal.startswith("map:"):
        try:
            return f"map:{int(goal[4:], 0):#04x}"
        except ValueError:
            return goal
    return goal


def _console_reasons(run_dir: Path) -> list[str]:
    """Scan console.log line by line (it can be tens of MB) for step errors and human press lines."""
    path = run_dir / "console.log"
    errors, human, first = 0, 0, ""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("[agent step error"):
                    errors += 1
                    first = first or line.strip()
                elif line.lstrip().startswith("human:"):
                    human += 1
    except OSError:
        return []
    out: list[str] = []
    if errors:
        out.append(f"{errors} agent step error(s) in console.log, first: {first[:200]}")
    if human:
        out.append(f"{human} human: press line(s) in console.log")
    return out


def judge_run(run_dir: Path, goal: str, budget: int) -> Verdict:
    """Pass only when every press is the agent's and ``goal`` was first reached at step <= ``budget``."""
    run_dir = Path(run_dir)
    skipped: dict = {}
    rows = jsonl(run_dir / "transitions.jsonl", skipped)
    reasons, non_agent = _press_reasons(rows, skipped.get("transitions.jsonl", 0))
    goal_reasons, goal_step = _goal_reasons(run_dir, normalize_goal(goal), budget)
    reasons += goal_reasons + _console_reasons(run_dir)
    return Verdict(passed=not reasons, reasons=reasons, goal_step=goal_step,
                   presses=len(rows), non_agent=non_agent)
