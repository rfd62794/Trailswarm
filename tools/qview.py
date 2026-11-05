"""Decode and edit tabular Q-models: the model's-eye view.

    uv run python tools/qview.py runs/rollout_menu/q_8894.tour.json --top 10
    uv run python tools/qview.py MODEL --obs "(1, 18, 10, 0, 1, 0, 3, 1, 3, 1, 9, 10, 11, 3)"
    uv run python tools/qview.py MODEL --set "(1,18,10,0,1,0,3,1,3,1,9,10,11,3)" A -5.0
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from pokeagent.qmodels import load_model, save_model
from pokeagent.screencontext import MenuKind, ScreenType

BUTTONS = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'A', 'B', 'START', 'SELECT']
MAPS = {0: 'pallet', 1: 'viridian', 2: 'pewter', 0x0C: 'route1', 0x0D: 'route2',
        0x25: 'house_f1', 0x26: 'house_f2', 0x28: 'oaks_lab', 0x36: 'pewter_gym'}
DIRS = {0: 'DOWN', 1: 'UP', 2: 'LEFT', 3: 'RIGHT'}
TILES = {0: '?', 1: '.', 2: '#', 3: '~'}  # unknown/walk/solid/grass


def decode_obs(obs: tuple) -> dict:
    out = {'map': MAPS.get(obs[0], hex(obs[0])), 'pos': (obs[1], obs[2]),
           'box': bool(obs[3]), 'facing': DIRS.get(obs[4], obs[4]),
           'battle': bool(obs[5]), 'hp_q': obs[6], 'bag_n': obs[7]}
    if len(obs) >= 14:
        out.update(screen=ScreenType(obs[8]).name, menu=MenuKind(obs[9]).name,
                   cursor=(obs[11], obs[12]), option=obs[13])
    if len(obs) >= 24:
        cells = [''.join(TILES.get(v, str(v)) for v in obs[14:17]),
                 ''.join(TILES.get(v, str(v)) for v in obs[17:20]),
                 ''.join(TILES.get(v, str(v)) for v in obs[20:23])]
        out.update(tiles=cells, blocked_mask=obs[23])
    if len(obs) > 24:
        out['rest'] = list(obs[24:])
    return out


def load(path):
    data = json.loads(Path(path).read_text())
    return data, data.get('schema'), data.get('actions', 6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('model')
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--obs')
    ap.add_argument('--set', nargs=3, metavar=('OBS', 'ACTION', 'VALUE'))
    ap.add_argument('--schema')
    ap.add_argument('--actions', type=int)
    args = ap.parse_args()

    data, schema, n_actions = load(args.model)
    schema = args.schema or schema
    n_actions = args.actions or n_actions
    table = load_model(args.model, schema, n_actions)

    if args.set:
        obs_s, act_s, val_s = args.set
        obs = ast.literal_eval(obs_s)
        key = tuple(obs) if isinstance(obs, (list, tuple)) else obs
        if key not in table:
            table[key] = [0.0] * n_actions
        idx = BUTTONS.index(act_s) if act_s.isalpha() else int(act_s)
        table[key][idx] = float(val_s)
        save_model(args.model, {k: list(v) for k, v in table.items()}, schema, n_actions)
        print(f"set {decode_obs(key)} {act_s} = {val_s}")
        return 0

    if args.obs:
        key = tuple(ast.literal_eval(args.obs))
        row = table.get(key)
        print(json.dumps({'obs': decode_obs(key), 'q': dict(zip(BUTTONS[:n_actions], row or []))}, indent=1))
        return 0

    ranked = sorted(table.items(), key=lambda kv: max(kv[1]), reverse=True)[: args.top or 0]
    for obs, row in ranked:
        best = BUTTONS[row.index(max(row))]
        print(f"{best:6} {max(row):8.3f}  {decode_obs(tuple(obs))}")
    print(f"states={len(table)} schema={schema} actions={n_actions}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
