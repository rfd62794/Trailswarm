"""Skill library management: promote trained tables into runs/skills/.

    uv run python tools/skills.py promote menu_tour runs/rollout_menu/q_8894.tour.json
    uv run python tools/skills.py list
    uv run python tools/skills.py best menu_tour runs/rollout_menu/q_889*.tour.json

A skill = Q table + manifest entry (schema, source, eval, promoted_at).
Once promoted, any agent can invoke it via --option <name>.
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import time
from pathlib import Path

SKILLS = Path('runs/skills')
MANIFEST = SKILLS / 'skills.json'


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def _write_manifest(m: dict) -> None:
    SKILLS.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1))


def _stats(qpath: str) -> dict:
    data = json.loads(Path(qpath).read_text())
    return {'schema': data.get('schema'), 'actions': data.get('actions'),
            'states': len(data.get('table', {})), 'source': qpath}


def promote(name: str, qpath: str, eval_stats: dict | None = None) -> dict:
    SKILLS.mkdir(parents=True, exist_ok=True)
    dest = SKILLS / f'{name}.json'
    shutil.copy2(qpath, dest)
    m = _manifest()
    m[name] = {**_stats(qpath), 'eval': eval_stats, 'promoted_at': time.time()}
    _write_manifest(m)
    return m[name]


def best(name: str, pattern: str) -> dict | None:
    """Pick the largest table matching a glob (proxy for most-learned) and promote it."""
    cands = [(Path(f).stat().st_size, f) for f in glob.glob(pattern)]
    if not cands:
        return None
    return promote(name, max(cands)[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['promote', 'list', 'best'])
    ap.add_argument('name', nargs='?')
    ap.add_argument('path', nargs='?')
    a = ap.parse_args()
    if a.cmd == 'list':
        print(json.dumps(_manifest(), indent=1))
    elif a.cmd == 'best':
        print(json.dumps(best(a.name, a.path), indent=1))
    else:
        print(json.dumps(promote(a.name, a.path), indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
