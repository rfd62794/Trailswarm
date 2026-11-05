from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from pokeagent.emulator import Button
from pokeagent.screentext import CHARMAP
from rl_env import ACTIONS, SegmentEnv


def probe_action(tilemap, mode):
    rows = [''.join(CHARMAP.get(b, ' ') for b in tilemap[i:i+20]).upper()
            for i in range(0, 360, 20)]
    text = ' '.join(rows)
    current = next((row.split('>', 1)[1].strip() for row in rows if '>' in row), '')
    if mode == 'escape' and 'FIGHT' in text and 'RUN' in text:
        if current.startswith('RUN'):
            return Button.A
        return Button.RIGHT if current.startswith('ITEM') else Button.DOWN
    if mode == 'lose' and ('GROWL' in text or 'TAIL WHIP' in text or 'LEER' in text):
        if current.startswith(('GROWL', 'TAIL WHIP', 'LEER')):
            return Button.A
        return Button.DOWN
    return Button.A


def run_probe(mode, state, max_steps=600, throttle_ms=4):
    env = SegmentEnv('roms/Pokemon Red.gb', state, lambda emu: False,
                     goal_name='battle', max_steps=max_steps, settle=16)
    env._goal_saved = True
    try:
        env.reset()
        if env.emu.read(0xD057) != 1:
            raise ValueError('Probe requires a wild encounter checkpoint')
        for _ in range(max_steps):
            button = probe_action(env.emu.read_range(0xC3A0, 360), mode)
            _, _, done, info = env.step(ACTIONS.index(button))
            time.sleep(throttle_ms/1000)
            if done or info['outcome'] != 'none':
                return {'probe': mode, 'steps': env.steps, 'goal_reached': env.goal_reached,
                        'outcome': info['outcome'], 'wild_wins': env.battle_tracker.wild_wins,
                        'battle_result_raw': env.emu.read(0xCF0B)}
        return {'probe': mode, 'steps': env.steps, 'outcome': 'timeout'}
    finally:
        env.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, default=Path('baselines/battle.state'))
    parser.add_argument('--mode', choices=['win', 'escape', 'lose', 'all'], default='all')
    args = parser.parse_args()
    modes = ['win', 'escape', 'lose'] if args.mode == 'all' else [args.mode]
    results = [run_probe(mode, args.state) for mode in modes]
    print(json.dumps(results, indent=2))
    expected = {'win': 'win', 'escape': 'disengaged', 'lose': 'blackout'}
    return int(any(row['outcome'] != expected[row['probe']] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
