"""Port legacy Q-tables into the current schema layout.

Old models died to schema changes, not bad learning. The porter projects old
obs keys into the new field layout: base 8 fields carry over verbatim, and
fields added later get defaults (cursor -1, unknown tiles, zero flags).
Values are discounted for staleness; multiple sources merge by mean.

    uv run python tools/port_models.py OLD.json --to runs/current.json --schema S --actions 8
    uv run python tools/port_models.py a.json b.json --to out.json --schema S --actions 8 --discount 0.5
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from pokeagent.qmodels import mean_tables, save_model

# obs layout: base(8) screen(6) spatial(10) combat(9) pixel(2) options(1+)
SCREEN_PAD = (0, 0, 0, -1, -1, -1)          # unknown screen/menu/conf/cursor/option
SPATIAL_PAD = (0,) * 10                   # unknown tile classes + empty block mask


def project(key: tuple, target_len: int) -> tuple:
    """Map an old-layout obs key into the current layout."""
    k = list(key[:8])                      # base fields always map
    rest = key[8:] if len(key) > 8 else ()
    if len(rest) >= 6:                     # old screen-context fields survive
        k += list(rest[:6])
    else:
        k += list(SCREEN_PAD)
    if len(rest) >= 16:                    # old spatial window survives
        k += list(rest[6:16])
    else:
        k += list(SPATIAL_PAD)
    k += list(rest[16:])                   # anything after (combat/extra) carries raw
    return tuple(k[:target_len]) + (0,) * max(0, target_len - len(k))


def load_raw(path: str) -> tuple[dict, int]:
    data = json.loads(Path(path).read_text())
    return {ast.literal_eval(k): list(v) for k, v in data['table'].items()}, data.get('actions', 6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('src', nargs='+')
    ap.add_argument('--to', required=True)
    ap.add_argument('--schema', required=True)
    ap.add_argument('--actions', type=int, required=True)
    ap.add_argument('--len', type=int, default=0, help='target obs length (default: keep max seen)')
    ap.add_argument('--discount', type=float, default=0.5)
    a = ap.parse_args()

    tables, n_acts = [], []
    for src in a.src:
        t, na = load_raw(src)
        n_acts.append(na)
        tables.append(t)
    merged = mean_tables(tables)
    tlen = a.len or max(len(k) for k in merged)

    out = {}
    for key, row in merged.items():
        nk = project(tuple(key), tlen)
        r = [v * a.discount for v in row[:a.actions]] + [0.0] * max(0, a.actions - len(row))
        cur = out.get(nk)
        out[nk] = [max(x, y) for x, y in zip(r, cur)] if cur else r
    save_model(a.to, {repr(k): v for k, v in out.items()}, a.schema, a.actions)
    print(f'ported {len(out)} states ({len(a.src)} sources, discount {a.discount}) -> {a.to}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
