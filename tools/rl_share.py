"""Community Q-pool: merge every learner's table into the shared best-known values.

    uv run python tools/rl_share.py            # merge runs/q_table_*.json -> runs/q_pool.json
    uv run python tools/rl_train.py --load-q runs/q_pool.json ...

Pooling beats single-sire: each (state,action) keeps the highest |Q| any
learner has found, so one explorer's discovery benefits the whole pool.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    pool: dict[str, list[float]] = defaultdict(lambda: [0.0] * 6)
    n = 0
    for f in sorted(Path("runs").glob("q_table_*.json")):
        if f.name == "q_pool.json":
            continue
        try:
            for k, v in json.loads(f.read_text()).items():
                for i, val in enumerate(v):
                    if abs(val) > abs(pool[k][i]):
                        pool[k][i] = val
        except Exception:
            pass
        n += 1
    Path("runs/q_pool.json").write_text(json.dumps(dict(pool)))
    print(f"pooled {n} tables -> runs/q_pool.json ({len(pool)} states)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
