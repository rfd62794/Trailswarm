"""Checkpoint-ladder orchestrator: mass-run a stage, bank the best verified
endpoint, reseat the fleet one stage deeper while a minority keeps refining
the stage behind.

Watches runs/checkpoints/rl_<segment>.state (written by SegmentEnv on first
goal reached). When the frontier advances, relaunches seats: MAJORITY on the
next stage starting from the newest checkpoint, MINORITY still on the stage
that just got solved (seeking a better/faster answer).

    uv run python tools/ladder.py            # run the orchestrator loop
    uv run python tools/ladder.py --once     # evaluate once, print decision
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# Ordered curriculum: (segment, seed checkpoint). rl_<seg>.state gates the next stage.
LADDER = [  # travel chain only; menu_tour stays a specialist skill, not a gate
    ('left_house', 'baselines/bedroom.state'),
    ('to_viridian', 'runs/checkpoints/rl_left_house.state'),
    ('to_route2', 'runs/checkpoints/rl_to_viridian.state'),
    ('to_pewter', 'runs/checkpoints/rl_to_route2.state'),
    ('campaign', 'runs/checkpoints/rl_to_pewter.state'),
]
PORTS = [8890, 8891, 8892, 8893, 8894, 8895]
FRONTIER_SEATS = 4  # majority push forward; the rest refine the previous stage
POLL_S = 60
STATUS = Path('runs/ladder.json')


def _eval_scores() -> dict:
    """port -> latest greedy win_rate from seat status."""
    scores = {}
    for f in Path('runs').glob('rlstatus_*.json'):
        try:
            s = json.loads(f.read_text())
            ev = s.get('evaluation') or {}
            scores[f.stem.split('_')[1]] = ev.get('win_rate', 0.0) or 0.0
        except Exception:
            continue
    return scores


def best_checkpoint(seg: str) -> str | None:
    """Best-scoring candidate rl_<seg>_<pid>.state, else the canonical rl_<seg>.state."""
    scores = _eval_scores()
    reg = json.loads(Path('runs/rl_agents.json').read_text()) if Path('runs/rl_agents.json').exists() else {}
    pid_score = {str(v.get('pid')): scores.get(p, 0.0) for p, v in reg.items()}
    cands = []
    for f in Path('runs/checkpoints').glob(f'rl_{seg}_*.state'):
        pid = f.stem.rsplit('_', 1)[-1]
        cands.append((pid_score.get(pid, 0.0), str(f)))
    if cands:
        return max(cands)[1]
    canon = Path(f'runs/checkpoints/rl_{seg}.state')
    return str(canon) if canon.exists() else None


def frontier() -> int:
    """Index of the deepest stage whose checkpoint does NOT yet exist (the stage to train)."""
    for i, (seg, _) in enumerate(LADDER):
        if best_checkpoint(seg) is None:
            return i
    return len(LADDER) - 1


def promote_skills() -> None:
    """Completed stages promote their best seat table into runs/skills/ as invocable options."""
    from skills import best
    for i, (seg, _) in enumerate(LADDER[:frontier()]):
        try:
            best(seg, f'runs/ladder/q_*.{seg}.json')
        except Exception:
            continue


def seat_plan() -> list[dict]:
    f = frontier()
    plan = []
    for i, port in enumerate(PORTS):
        idx = min(f, len(LADDER) - 1) if i < FRONTIER_SEATS else max(0, f - 1)
        seg = LADDER[idx][0]
        # frontier starts from the prior stage's best banked checkpoint; seed at the base
        prior = best_checkpoint(LADDER[idx - 1][0]) if idx > 0 else None
        start = prior or LADDER[idx][1]
        plan.append({'port': port, 'segment': seg, 'state': start})
    return plan


def launch(port: int, segment: str, state: str) -> None:
    steps = '300' if segment.startswith('menu_') else '5000'
    args = [sys.executable, 'tools/rl_train.py', '--segment', segment, '--state', state,
            '--episodes', '500', '--evals', '12', '--max-steps', steps,
            '--frame-port', str(port), '--seed', str(port + 2000), '--publish-fps', '15',
            '--full-res', '--throttle-ms', '20', '--share-every', '5', '--n-step', '3',
            '--double-q', '--trace', '--eps-decay-episodes', '40', '--eval-every', '10',
            '--periodic-evals', '2', '--repeat-penalty', '0.01', '--repeat-threshold', '8',
            '--interact-limit', '24', '--save-q', f'runs/ladder/q_{port}.{segment}.json',
            '--tag', f'{segment[:12]}-{port}']
    if segment != 'menu_tour':
        args += ['--battle-learning', '--screen-context', '--spatial-context',
                 '--combat-context', '--menu-controls']
    subprocess.Popen(args, cwd=Path(__file__).resolve().parents[1])


def write_status(plan: list[dict]) -> None:
    STATUS.parent.mkdir(exist_ok=True)
    STATUS.write_text(json.dumps({'frontier': frontier(), 'plan': plan,
                                  'updated_at': time.time()}, indent=1))


def main() -> int:
    once = '--once' in sys.argv
    current: dict[int, str] = {}
    while True:
        plan = seat_plan()
        if not once:
            for seat in plan:
                if current.get(seat['port']) != seat['segment']:
                    launch(seat['port'], seat['segment'], seat['state'])
                    current[seat['port']] = seat['segment']
                    time.sleep(1)
        promote_skills()
        write_status(plan)
        if once:
            print(json.dumps({'frontier': frontier(), 'plan': plan}, indent=1))
            return 0
        time.sleep(POLL_S)


if __name__ == '__main__':
    raise SystemExit(main())
