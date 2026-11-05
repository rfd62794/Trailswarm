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
LADDER = [
    ('menu_tour', 'baselines/bedroom.state'),
    ('to_route1', 'baselines/bedroom.state'),
    ('to_viridian', 'runs/checkpoints/rl_to_route1.state'),
    ('to_route2', 'runs/checkpoints/rl_to_viridian.state'),
    ('to_pewter', 'runs/checkpoints/rl_to_route2.state'),
    ('campaign', 'runs/checkpoints/rl_to_pewter.state'),
]
PORTS = [8890, 8891, 8892, 8893, 8894, 8895]
FRONTIER_SEATS = 4  # majority push forward; the rest refine the previous stage
POLL_S = 60
STATUS = Path('runs/ladder.json')


def frontier() -> int:
    """Index of the deepest stage whose checkpoint does NOT yet exist (the stage to train)."""
    for i, (seg, _) in enumerate(LADDER):
        if not Path(f'runs/checkpoints/rl_{seg}.state').exists():
            return i
    return len(LADDER) - 1


def seat_plan() -> list[dict]:
    f = frontier()
    plan = []
    for i, port in enumerate(PORTS):
        if i < FRONTIER_SEATS:
            seg, _ = LADDER[min(f, len(LADDER) - 1)]
            start = LADDER[max(0, f - 1)][1] if f > 0 else LADDER[0][1]
            start = f'runs/checkpoints/rl_{LADDER[f-1][0]}.state' if f > 0 else LADDER[0][1]
        else:  # refinement seat: one stage behind the frontier, from its own seed
            idx = max(0, f - 1)
            seg = LADDER[idx][0]
            start = LADDER[max(0, idx - 1)][1] if idx > 0 else LADDER[0][1]
            if idx > 0:
                start = f'runs/checkpoints/rl_{LADDER[idx-1][0]}.state'
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
        write_status(plan)
        if once:
            print(json.dumps({'frontier': frontier(), 'plan': plan}, indent=1))
            return 0
        time.sleep(POLL_S)


if __name__ == '__main__':
    raise SystemExit(main())
