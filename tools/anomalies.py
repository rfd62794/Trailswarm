"""Summarise runs/anomalies.jsonl: counts by type / map / cause hint, and the replayable save states.

    uv run python tools/anomalies.py [--runs runs] [--type npc_in_doorway] [--limit 20]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(runs: Path) -> list[dict]:
    path = runs / "anomalies.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a half-written line from a live run
    return out


def summarise(records: list[dict], kind: str | None = None, limit: int = 20) -> str:
    recs = [r for r in records if kind in (None, r.get("type"))]
    if not recs:
        return "no anomalies recorded"
    lines = [f"{len(recs)} anomalies in {len({r.get('run') for r in recs})} run(s)"]
    for title, key in (("by type", lambda r: r["type"]), ("by map", lambda r: f"0x{r['map']:02X}"),
                       ("by cause hint", lambda r: r.get("cause_hint", "unknown"))):
        lines.append(f"{title}: " + ", ".join(f"{k}={n}" for k, n in Counter(key(r) for r in recs).most_common()))
    lines.append("save states (replay with emu.load_state):")
    for r in recs[-limit:]:
        lines.append(f"  {r['type']:<20} map=0x{r['map']:02X} ({r['x']},{r['y']}) step={r['step']} cause={r.get('cause_hint')} "
                     f"state={r.get('state')} png={r.get('png')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--type", default=None)
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args(argv)
    print(summarise(load(Path(a.runs)), a.type, a.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
