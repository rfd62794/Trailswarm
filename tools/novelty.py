"""Novelty table and discovery log, read-only except `backfill` (which only creates a missing runs/novelty.json).

    uv run python tools/novelty.py top [-n 25]               rarest features recently found; explorer vs exploiter find rate
    uv run python tools/novelty.py discoveries [--since H]   flagged events (glitch maps, duplicated items, ...), newest last
    uv run python tools/novelty.py backfill                  build the count table from existing runs (diff if one exists)

--runs DIR points at another runs/ directory (default: runs/ beside this repo).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent.novelty import backfill as bf  # noqa: E402
from pokeagent.novelty.discoveries import LOG_NAME  # noqa: E402
from pokeagent.novelty.features import kind  # noqa: E402
from pokeagent.novelty.store import load_table  # noqa: E402
from pokeagent.qmodels import atomic_json  # noqa: E402


def _names() -> dict:
    out = {"m": json.loads((ROOT / "src" / "pokeagent" / "atlas" / "map_names.json").read_text(encoding="utf-8"))}
    try:
        kb = json.loads((ROOT / "kb" / "rom_tables.json").read_text(encoding="utf-8"))
        out["i"] = {k: v["name"] for k, v in kb["items"].items()}
        out["so"] = out["ss"] = kb["name_of_internal"]
        out["mv"] = {k: v["name"] for k, v in kb["moves"].items()}
    except (OSError, ValueError, KeyError):
        pass
    return out


def describe(key: str, names: dict) -> str:
    k, _, rest = key.partition(":")
    if k == "t":
        m, x, y = rest.split(":")
        return f"tile {names['m'].get(m, m)} ({x},{y})"
    if k == "w":
        a, b = rest.split(">")
        return f"warp {names['m'].get(a, a)} -> {names['m'].get(b, b)}"
    if k == "f":
        n = int(rest)
        return f"event flag 0x{0xD747 + n // 8:04X} bit {n % 8}"
    label = {"m": "map", "i": "item", "so": "own", "ss": "seen", "mv": "move"}.get(k, k)
    return f"{label} {names.get(k, {}).get(rest, rest)}"


def cmd_top(a) -> int:
    t = load_table(Path(a.runs) / "novelty.json")
    names = _names()
    counts, first = t["counts"], t["first"]
    if not counts:
        print("novelty table is empty (run `backfill`, or start a swarm with --novelty)")
        return 0
    by_kind: dict = {}
    for k in counts:
        by_kind[kind(k)] = by_kind.get(kind(k), 0) + 1
    print("features: " + ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items(), key=lambda kv: -kv[1])))
    rows = sorted((k for k in counts if kind(k) != "t"), key=lambda k: (counts[k], -first.get(k, [0])[0]))
    print(f"\nrarest {a.n} non-tile features (count = runs that found it; newest first among ties):")
    for k in rows[: a.n]:
        ts, role, run = first.get(k, [0, "", ""])
        when = time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "unknown"
        print(f"  {counts[k]:>4}  {describe(k, names):<46} first {when} by {role or '?'} ({run})")
    print("\nfirst finds by role (what each role found before anyone else did):")
    runs = t["role_runs"]
    for role in sorted(set(runs) | {f[1] for f in first.values()}):
        mine = [k for k, f in first.items() if f[1] == role]
        nt = sum(kind(k) != "t" for k in mine)
        n = runs.get(role, 0)
        rate = f"{nt / n:.2f} non-tile / run, {len(mine) / n:.1f} any / run" if n else "no run count"
        print(f"  {role or '?':<10} runs {n:>5}   first finds {len(mine):>6} ({nt} non-tile)   {rate}")
    return 0


def cmd_discoveries(a) -> int:
    path = Path(a.runs) / LOG_NAME
    cut = time.time() - a.since * 3600 if a.since else 0
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("t", 0) >= cut:
                rows.append(r)
    except OSError:
        pass
    if not rows:
        print("no discoveries" + (f" in the last {a.since:g}h" if a.since else ""))
        return 0
    names = _names()
    for r in rows:
        when = time.strftime("%m-%d %H:%M", time.localtime(r.get("t", 0)))
        print(f"{when} {r['kind']:<17} {describe(r['feature'], names) if r['feature'] != 'money' else 'money':<34} "
              f"{r['before']} -> {r['after']}  [{r['role'] or '?'} {r['run']} step {r['step']}] {r.get('state') or '(no state saved)'}")
    print(f"\n{len(rows)} flagged. Review only: these saves may be glitch-corrupted and are never checkpoints.")
    return 0


def cmd_backfill(a) -> int:
    runs = Path(a.runs)
    table = bf.build_table(runs)
    out = runs / "novelty.json"
    n = len(table["merged"])
    if out.exists():
        print(f"{out} exists; not writing. A rebuild from {n} runs would change it by: {json.dumps(bf.diff_tables(load_table(out), table))}")
        return 0
    atomic_json(out, table)
    print(f"wrote {out}: {len(table['counts'])} features from {n} runs")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=str(ROOT / "runs"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("top"); p.add_argument("-n", type=int, default=25); p.set_defaults(fn=cmd_top)
    p = sub.add_parser("discoveries"); p.add_argument("--since", type=float, default=0, help="hours"); p.set_defaults(fn=cmd_discoveries)
    sub.add_parser("backfill").set_defaults(fn=cmd_backfill)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
