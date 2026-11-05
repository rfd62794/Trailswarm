"""Run-level RL analysis: where winning runs align, where they diverge, and
where the pooled learners' policies agree.

    uv run python tools/rl_analyze.py --segment potion
    uv run python tools/rl_analyze.py --segment potion --top 10

Three lenses on the same data:
  1. Consensus corridor -- (map,x,y) positions visited by >=50% of winning runs,
     ordered by median first-visit step. These are gold-path candidates.
  2. Divergence point -- the earliest step index where winners stop sharing a
     position; the bottleneck where exploration matters most.
  3. Policy agreement -- across runs/qshare/<segment>_*.json pool tables, the
     fraction of shared states where every learner's argmax action matches.
     Unanimous states are settled; contested states are the frontier.
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_traces(seg: str, schema: str | None = None) -> list[dict]:
    traces = []
    tdir = Path("runs/traces")
    if not tdir.exists():
        return traces
    for f in tdir.glob(f"{seg}_*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                trace = json.loads(line)
                if trace.get('schema') == schema:
                    traces.append(trace)
            except Exception:
                pass
    return traces


def pos_of(entry: list) -> tuple:
    return tuple(entry[:3])  # (map, x, y)


def corridor(winners: list[dict]) -> None:
    cover: dict[tuple, list[int]] = defaultdict(list)  # pos -> first-visit step per run
    for t in winners:
        seen = set()
        for i, e in enumerate(t["path"]):
            p = pos_of(e)
            if p not in seen:
                seen.add(p)
                cover[p].append(i)
    n = len(winners)
    rows = sorted(((p, len(v), sorted(v)[len(v) // 2]) for p, v in cover.items() if len(v) >= n / 2),
                  key=lambda r: r[2])
    print(f"\n== consensus corridor ({len(winners)} winning runs; positions in >=50% of them) ==")
    for p, c, med in rows[:30]:
        print(f"  map{p[0]:>3} ({p[1]:>2},{p[2]:>2})  in {c}/{n} runs, median step {med}")


def divergence(winners: list[dict]) -> None:
    # earliest step index where the modal position is shared by <50% of runs
    by_step: dict[int, Counter] = defaultdict(Counter)
    for t in winners:
        for i, e in enumerate(t["path"]):
            by_step[i][pos_of(e)] += 1
    n = len(winners)
    for i in sorted(by_step):
        top, cnt = by_step[i].most_common(1)[0]
        n = sum(by_step[i].values())
        if cnt < n / 2:
            print(f"\n== divergence at step {i}: only {cnt}/{n} runs share map{top[0]} ({top[1]},{top[2]}); "
                  f"{len(by_step[i])} distinct positions ==")
            for p, c in by_step[i].most_common(6):
                print(f"    map{p[0]:>3} ({p[1]:>2},{p[2]:>2}): {c}")
            return
    print("\n== no divergence: all winning runs stay aligned ==")


def agreement(seg: str, schema: str | None = None) -> None:
    sdir = Path("runs/qshare") / schema if schema else Path("runs/qshare")
    tables = []
    if sdir.exists():
        for f in sorted(sdir.glob(f"{seg}_*.json")):
            try:
                if schema:
                    from pokeagent.qmodels import load_model
                    payload = json.loads(f.read_text())
                    table = load_model(f, schema, payload['actions'])
                else:
                    table = {ast.literal_eval(k): v for k, v in json.loads(f.read_text()).items()}
                tables.append((f.stem, table))
            except Exception:
                pass
    if len(tables) < 2:
        print(f"\n== policy agreement: need >=2 pool tables for '{seg}', found {len(tables)} ==")
        return
    shared = set(tables[0][1])
    for _, t in tables[1:]:
        shared &= set(t)
    if not shared:
        print(f"\n== policy agreement: no state overlap between the {len(tables)} '{seg}' tables ==")
        return
    unanimous = contested = 0
    contest_states = []
    for s in shared:
        argmaxes = [max(range(len(t[s])), key=lambda i: t[s][i]) for _, t in tables]
        if len(set(argmaxes)) == 1:
            unanimous += 1
        else:
            contested += 1
            contest_states.append((s, Counter(argmaxes)))
    pct = 100 * unanimous / len(shared)
    print(f"\n== policy agreement across {len(tables)} '{seg}' learners ==")
    print(f"  shared states {len(shared)}: {unanimous} unanimous ({pct:.0f}%), {contested} contested")
    for s, c in sorted(contest_states, key=lambda x: -sum(x[1].values()))[:10]:
        acts = ", ".join(f"a{a}x{n}" for a, n in c.most_common())
        print(f"    map{s[0]:>3} ({s[1]:>2},{s[2]:>2}) box={s[3]} face={s[4]}: {acts}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", required=True)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument('--schema', default=None)
    a = ap.parse_args()

    traces = load_traces(a.segment, a.schema)
    winners = [t for t in traces if t.get("won")]
    steps = [t["steps"] for t in winners]
    print(f"segment {a.segment}: {len(traces)} traced episodes, {len(winners)} wins"
          + (f", steps min {min(steps)} med {sorted(steps)[len(steps)//2]} max {max(steps)}" if steps else ""))
    if len(winners) >= 2:
        corridor(winners)
        divergence(winners)
    agreement(a.segment, a.schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
