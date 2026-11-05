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

from pokeagent.qdecode import BUTTONS, decode_obs
from pokeagent.qmodels import load_model, save_model


def load(path):
    data = json.loads(Path(path).read_text())
    return data, data.get('schema'), data.get('actions', 6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('model')
    ap.add_argument('--top', type=int, default=0)
    ap.add_argument('--obs')
    ap.add_argument('--set', nargs=3, metavar=('OBS', 'ACTION', 'VALUE'))
    ap.add_argument('--patch-save', action='store_true',
                    help='set A <= -2 at every START-menu state whose cursor sits on SAVE')
    ap.add_argument('--schema')
    ap.add_argument('--actions', type=int)
    args = ap.parse_args()

    data, schema, n_actions = load(args.model)
    schema = args.schema or schema
    n_actions = args.actions or n_actions
    table = load_model(args.model, schema, n_actions)

    if args.set or args.patch_save:
        if args.patch_save:
            a_idx = BUTTONS.index('A')
            hits = [k for k in table if len(tuple(k)) >= 14 and tuple(k)[9] == 1 and tuple(k)[13] == 3]
            for k in hits:
                table[k][a_idx] = min(table[k][a_idx], -2.0)
            save_model(args.model, {repr(k): list(v) for k, v in table.items()}, schema, n_actions)
            print(f"patched {len(hits)} SAVE-cursor states in {args.model}")
            return 0
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
