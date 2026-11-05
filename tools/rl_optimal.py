from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from navgrid import load_grids, optimal_steps


def compare(maps, start, goals, traces=()):
    distance = optimal_steps(load_grids(maps), start, goals)
    solved = [t['steps'] for t in traces if t.get('won') and t.get('path')
              and tuple(t['path'][0][:3]) == tuple(start)]
    return {'metric': 'learned_directed_graph_distance',
            'not_proven_button_optimum': True,
            'maps_digest': hashlib.sha256(Path(maps).read_bytes()).hexdigest(),
            'start': list(start), 'graph_steps': distance,
            'solved_runs': len(solved), 'best_observed_presses': min(solved) if solved else None,
            'mean_observed_presses': sum(solved)/len(solved) if solved else None,
            'limitations': ['unknown edges', 'menus and facing omitted', 'action duration',
                            'NPC and battle state', 'historical collision evidence']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--maps', default='runs/maps.json')
    parser.add_argument('--start', nargs=3, type=int, required=True, metavar=('MAP', 'X', 'Y'))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--goal', nargs=3, type=int, metavar=('MAP', 'X', 'Y'))
    target.add_argument('--goal-map', type=int)
    parser.add_argument('--trace', type=Path)
    args = parser.parse_args()
    goals = [tuple(args.goal)] if args.goal else [('map', args.goal_map)]
    traces = []
    if args.trace:
        for number, line in enumerate(args.trace.read_text().splitlines(), 1):
            try:
                traces.append(json.loads(line))
            except ValueError as exc:
                parser.error(f'Malformed trace at line {number}: {exc}')
    print(json.dumps(compare(args.maps, args.start, goals, traces), indent=2))


if __name__ == '__main__':
    main()
