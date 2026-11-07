"""``pokeagent review replay``: determinism check - re-run the same start state + seed headlessly
for N steps and diff the decision stream against the original's first N.

The emulator call is thin and INJECTED: ``runner(argv, out_dir) -> list[dict] | None`` is the only
place a subprocess lives; the pure functions (``compare_streams``, ``replay_command``,
``locate_start_state``, ``run_replay`` with an injected runner) are what tests cover.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pokeagent.review.load import jsonl, load_json

COMPARE_FIELDS = ("button", "map", "x", "y", "outcome")   # the decisions.jsonl press identity
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Divergence:
    step: int | None
    field: str            # which of COMPARE_FIELDS differed ("length" when one stream ran out)
    a: dict
    b: dict
    rule_a: str | None
    rule_b: str | None
    agreed_steps: int

    def to_json(self) -> dict:
        return {"step": self.step, "field": self.field, "a": self.a, "b": self.b,
                "rule_a": self.rule_a, "rule_b": self.rule_b, "agreed_steps": self.agreed_steps}


def compare_streams(a: list[dict], b: list[dict], n: int) -> Divergence | None:
    """FIRST divergence over the first ``n`` press rows (extra keys tolerated). None when the
    first ``n`` rows (or all rows when fewer) are identical; a length mismatch before ``n``
    is itself a divergence (``field == "length"``)."""
    for i in range(min(n, len(a), len(b))):
        for f in COMPARE_FIELDS:
            if a[i].get(f) != b[i].get(f):
                return Divergence(a[i].get("step", i + 1), f, a[i], b[i],
                                  a[i].get("rule"), b[i].get("rule"), i)
    if len(a) != len(b) and min(len(a), len(b)) < n:
        i = min(len(a), len(b))
        ra, rb = (a[i] if i < len(a) else {}), (b[i] if i < len(b) else {})
        return Divergence((ra or rb).get("step", i + 1), "length", ra, rb,
                          ra.get("rule"), rb.get("rule"), i)
    return None


def replay_command(meta: dict, start_state: Path, steps: int, out_dir: Path,
                   python: str = "uv run python") -> list[str]:
    """The ``tools/explore_headless.py`` argv that re-runs ``meta``'s start state for ``steps``
    presses (seed, starter, stop_at_goal and the meta's boolean flags). ``out_dir`` is handed to
    the runner: explore_headless keeps no run dir, so the runner parses its printed work dir."""
    cmd = [*python.split(), str(REPO_ROOT / "tools" / "explore_headless.py"),
           "--state", str(start_state), "--steps", str(steps)]
    if meta.get("seed") is not None:
        cmd += ["--seed", str(meta["seed"])]
    if meta.get("starter"):
        cmd += ["--starter", str(meta["starter"])]
    if meta.get("stop_at_goal"):
        cmd += ["--stop-at-goal", str(meta["stop_at_goal"])]
    for flag, key in (("--adaptive", "adaptive"), ("--fast-text", "fast_text"),
                      ("--bandit", "bandit"), ("--par-follow", "par_follow"),
                      ("--novelty", "novelty")):
        if meta.get(key):
            cmd.append(flag)
    maps = Path(start_state).parent / "maps.json"  # the seg job kept the input memory beside the state
    if maps.is_file():
        cmd += ["--maps-copy", str(maps)]
    return cmd


def locate_start_state(meta: dict, runs_dir: Path) -> Path | None:
    """The kept start-state copy under ``runs/segments/inputs/<tag>/`` (job.json's start_name, or a
    sole .state file). None when there is no kept copy - never the current checkpoint, never a guess."""
    tag = str(meta.get("tag") or "")
    if not tag:
        return None
    d = Path(runs_dir) / "segments" / "inputs" / re.sub(r"[^A-Za-z0-9_.@-]", "_", tag)
    if not d.is_dir():
        return None
    try:
        rec = json.loads((d / "job.json").read_text(encoding="utf-8"))
        cand = d / rec["start_name"]
        if cand.is_file():
            return cand
    except (OSError, ValueError, KeyError):
        pass
    states = sorted(d.glob("*.state"))
    return states[0] if len(states) == 1 else None


@dataclass
class ReplayReport:
    status: str     # identical | diverged | start_state_unrecoverable | runner_unavailable
    run: str
    steps: int
    divergence: Divergence | None = None
    warning: str | None = None
    command: list[str] | None = None
    reason: str | None = None

    def to_json(self) -> dict:
        out = {"status": self.status, "run": self.run, "steps": self.steps}
        if self.reason:
            out["reason"] = self.reason
        if self.warning:
            out["warning"] = self.warning
        if self.command:
            out["command"] = self.command
        if self.divergence:
            out["divergence"] = self.divergence.to_json()
        return out


def _default_runner(argv: list[str], out_dir: Path) -> list[dict] | None:
    """Thin subprocess wrapper for the argv ``replay_command`` built: run it, parse the printed
    JSON's ``work`` dir, read its decisions.jsonl (press rows only). None when the stream is not
    recoverable - ``run_replay`` then reports ``runner_unavailable`` with the command it ran."""
    try:
        proc = subprocess.run(argv, cwd=out_dir, capture_output=True, text=True)
        work = Path(json.loads(proc.stdout[proc.stdout.index("{"):])["work"])
        rows = [r for r in jsonl(work / "decisions.jsonl") if "event" not in r]
        return rows or None
    except (OSError, ValueError, KeyError):
        return None


def run_replay(run_dir, steps, runs_dir, runner=None, head_sha=None) -> ReplayReport:
    """Load the original's first ``steps`` press rows, resolve the kept start state, run the
    injected (or default subprocess) runner, compare. ``head_sha`` comes from the CLI wrapper
    (the only place ``git rev-parse HEAD`` may be called); a mismatch is a warning, not an error."""
    run_dir = Path(run_dir)
    meta = load_json(run_dir / "meta.json")
    original = [r for r in jsonl(run_dir / "decisions.jsonl") if "event" not in r][:steps]
    state = locate_start_state(meta, Path(runs_dir))
    if state is None:
        return ReplayReport("start_state_unrecoverable", run_dir.name, steps,
                            reason="no kept start copy under runs/segments/inputs/<tag>/")
    warning = None
    if head_sha and meta.get("git_sha") and meta["git_sha"] != head_sha:
        warning = "code differs: divergence is expected"
    out_dir = Path(tempfile.mkdtemp(prefix="review-replay-"))
    argv = replay_command(meta, state, steps, out_dir)
    try:
        replayed = (runner or _default_runner)(argv, out_dir)
    except Exception:  # noqa: BLE001 - an injected runner's failure is unavailability, not a crash
        replayed = None
    if replayed is None:
        return ReplayReport("runner_unavailable", run_dir.name, steps, warning=warning,
                            command=argv, reason="runner produced no decisions.jsonl")
    div = compare_streams(original, replayed, steps)
    return ReplayReport("diverged" if div else "identical", run_dir.name, steps,
                        divergence=div, warning=warning, command=argv)
