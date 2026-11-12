"""Hands-off regression: run each case in a scratch copy of the repo and judge that the agent alone got there.

    uv run python tools/hands_off_check.py                     # every case in tools/hands_off_cases.json
    uv run python tools/hands_off_check.py --case red_bedroom_potion_cold
    uv run python tools/hands_off_check.py --keep               # keep the scratch dir and print its path
    uv run python tools/hands_off_check.py --judge RUN_DIR --goal potion --budget 105   # judge only, run nothing

A case whose gitignored inputs (ROM, baseline state, kb) are absent is skipped with a reason.
The live runs/ and kb/ are only ever read, as copies into the scratch tree.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokeagent.review.hands_off import judge_run  # noqa: E402
from pokeagent.review.hands_off_cases import (  # noqa: E402
    GAME_ROMS, Case, build_argv, load_cases, skip_reason, state_path)

CASES = ROOT / "tools" / "hands_off_cases.json"
TIMEOUT = 600


@dataclass(frozen=True)
class CaseRun:
    proc: object | None       # the completed process, None on a timeout
    error: str | None         # last 400 chars of stderr on a non-zero exit or timeout


def _tail(text) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return (text or "")[-400:]


def copy_inputs(case: Case, scratch: Path, root: Path = ROOT) -> None:
    """Mirror tests/test_golden_red.py: tools/, src/, ROM, state (+meta), kb/, empty runs/."""
    for d in ("tools", "src"):
        shutil.copytree(root / d, scratch / d, ignore=shutil.ignore_patterns("__pycache__"))
    state = state_path(case)
    for rel in (GAME_ROMS[case.game], state, state + ".meta.json"):
        if (root / rel).exists():
            (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(root / rel, scratch / rel)
    shutil.copytree(root / "kb", scratch / "kb", ignore=shutil.ignore_patterns("__pycache__"))
    (scratch / "runs").mkdir()
    if case.memory == "live":
        shutil.copy(root / "runs" / "maps.json", scratch / "runs" / "maps.json")


def run_case(case: Case, index: int, scratch: Path, runner=subprocess.run) -> CaseRun:
    """The only place the demo is started; tests pass a fake ``runner``."""
    argv = [sys.executable, *build_argv(case, index)]
    try:
        proc = runner(argv, cwd=scratch, check=False, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        return CaseRun(None, _tail(f"timeout after {exc.timeout}s; " + _tail(exc.stderr)))
    if proc.returncode != 0:
        return CaseRun(proc, _tail(proc.stderr))
    return CaseRun(proc, None)


def check_case(case: Case, index: int, scratch: Path, runner=subprocess.run) -> tuple[str, str]:
    """Run, find the one new runs/explore-* dir, judge. Returns (status, printed line)."""
    runs = scratch / "runs"
    before = set(runs.glob("explore-*"))
    result = run_case(case, index, scratch, runner)
    if result.error is not None:
        return "error", f"ERROR {case.name}: {result.error}"
    new = sorted(set(runs.glob("explore-*")) - before)
    if len(new) != 1:
        return "fail", f"FAIL {case.name}: expected one new runs/explore-* dir, found {len(new)}"
    v = judge_run(new[0], case.goal, case.budget)
    if v.passed:
        return "pass", (f"PASS {case.name}: {case.goal} at step {v.goal_step} of budget {case.budget}, "
                        f"0 non-agent presses")
    return "fail", f"FAIL {case.name}: {'; '.join(v.reasons)}\n  run dir: {new[0]}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", help="run only this case name")
    ap.add_argument("--keep", action="store_true", help="keep the scratch dir and print its path")
    ap.add_argument("--judge", metavar="RUN_DIR", help="judge an existing run dir; run nothing")
    ap.add_argument("--goal", help="goal for --judge")
    ap.add_argument("--budget", type=int, help="step budget for --judge")
    args = ap.parse_args(argv)

    if args.judge:
        if not args.goal or args.budget is None:
            ap.error("--judge needs --goal and --budget")
        v = judge_run(Path(args.judge), args.goal, args.budget)
        if v.passed:
            print(f"PASS {args.judge}: {args.goal} at step {v.goal_step} of budget {args.budget}, "
                  f"0 non-agent presses")
            return 0
        print(f"FAIL {args.judge}: {'; '.join(v.reasons)}")
        return 1

    cases = load_cases(CASES)
    if args.case:
        cases = [c for c in cases if c.name == args.case]
        if not cases:
            ap.error(f"no case named {args.case!r} in {CASES.name}")
    counts = {"pass": 0, "fail": 0, "skip": 0}
    for index, case in enumerate(cases):
        reason = skip_reason(case, ROOT)
        if reason:
            print(f"SKIP {case.name}: {reason}")
            counts["skip"] += 1
            continue
        scratch = Path(tempfile.mkdtemp(prefix="hands-off-"))
        try:
            copy_inputs(case, scratch)
            status, line = check_case(case, index, scratch)
        finally:
            if args.keep:
                print(f"  scratch: {scratch}")
            else:
                shutil.rmtree(scratch, ignore_errors=True)
        print(line)
        counts["pass" if status == "pass" else "fail"] += 1
    print(f"{counts['pass']} passed, {counts['fail']} failed, {counts['skip']} skipped")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
