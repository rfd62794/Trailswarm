"""Playback a traced episode: t | map pos | action | screen/menu.

    uv run python tools/trace_view.py runs/traces/to_viridian_8892.jsonl          # last episode
    uv run python tools/trace_view.py FILE --ep 12 --every 5                      # episode 12, every 5th step
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pokeagent.qdecode import BUTTONS, decode_obs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--ep', type=int, default=None)
    ap.add_argument('--every', type=int, default=1)
    a = ap.parse_args()

    lines = [json.loads(l) for l in Path(a.file).read_text().strip().splitlines() if l.strip()]
    ep = a.ep if a.ep is not None else lines[-1].get('ep')
    rec = next((r for r in reversed(lines) if r.get('ep') == ep), lines[-1])
    path, times = rec.get('path', []), rec.get('times', [])
    for i, row in enumerate(path):
        if i % a.every:
            continue
        obs, act = row[:-1], row[-1]
        d = decode_obs(obs)
        where = d.get('menu') or d.get('screen') or ''
        t = f'{times[i]:6.1f}s' if i < len(times) else '      '
        print(f"{t} {d['map']:10}{d['pos']} {BUTTONS[act] if act < len(BUTTONS) else f'opt{act}':7} "
              f"{where} opt{d.get('option')}")
    print(f"--- ep {rec.get('ep')} won={rec.get('won')} steps={rec.get('steps')} "
          f"dur={rec.get('duration')}s rewards={rec.get('rewards')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
