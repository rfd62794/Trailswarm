"""Swarm learning: run N headless explorers in parallel, each from the shared memory, then merge what they learned.

    uv run python tools/swarm.py --agents 4 --steps 400          # ~N x faster learning than one watched run
    uv run python tools/swarm.py --merge-only                     # just fold runs/swarm/agent*.json into runs/maps.json

Each agent gets its own copy of runs/maps.json, a different seed and starter, a different control port
(8800+i) and its own transitions file (runs/explore-<ts>/, as always). When all finish, merge_memory folds
every agent's memory back into runs/maps.json: visit counts add, walls/warps/interactions/tile types union,
demonstrations union (with their grades), so the next watched run starts from everything the swarm found.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def merge_memory(dst: dict, src: dict) -> dict:
    for mid, s in src.get("maps", {}).items():
        d = dst.setdefault("maps", {}).setdefault(mid, {"visited": {}, "blocked": [], "warps": {}, "last_seen": 0})
        for k, n in s.get("visited", {}).items():
            d["visited"][k] = max(d["visited"].get(k, 0), n)  # counts are per-run observations; keep the max, not the sum
        for k in s.get("blocked", []):
            if k not in d["blocked"]:
                d["blocked"].append(k)
        d["warps"].update(s.get("warps", {}))
        wt = d.setdefault("warp_taken", {})
        for k, n in s.get("warp_taken", {}).items():
            wt[k] = wt.get(k, 0) + n
        inter = d.setdefault("interactions", {})
        for k, e in s.get("interactions", {}).items():
            cur = inter.setdefault(k, {"count": 0, "text": "", "presses": [], "menus": [], "choices": []})
            cur["count"] = cur.get("count", 0) + e.get("count", 0)
            if len(e.get("text", "")) > len(cur.get("text", "")):
                cur["text"] = e["text"]
            for key in ("presses", "menus", "choices", "effects"):
                for v in e.get(key, []) or []:
                    if v not in cur.setdefault(key, []):
                        cur[key].append(v)
            cur["presses"] = cur.get("presses", [])[-10:]
        demos = d.setdefault("demos", [])
        for dm in s.get("demos", []):
            same = next((x for x in demos if x["at"] == dm["at"] and x["buttons"] == dm["buttons"]), None)
            if same:
                same["grade"] = same.get("grade", 0) + dm.get("grade", 0); same["replays"] = same.get("replays", 0) + dm.get("replays", 0)
            else:
                demos.append(dm)
        d["last_seen"] = max(d.get("last_seen", 0), s.get("last_seen", 0))
    tt = dst.setdefault("tile_types", {})
    for ts, table in src.get("tile_types", {}).items():
        t = tt.setdefault(ts, {})
        for k, e in table.items():
            cur = t.setdefault(k, {"solid": 0, "walkable": 0})
            cur["solid"] += e.get("solid", 0); cur["walkable"] += e.get("walkable", 0)
    dst["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--maps", default="runs/maps.json")
    a = ap.parse_args()
    shared = ROOT / a.maps
    swarm_dir = ROOT / "runs" / "swarm"; swarm_dir.mkdir(parents=True, exist_ok=True)

    if not a.merge_only:
        procs = []
        for i in range(a.agents):
            own = swarm_dir / f"agent{i}.json"
            if shared.exists():
                shutil.copy(shared, own)
            starter = ["bulbasaur", "charmander", "squirtle"][i % 3]
            cmd = [sys.executable, str(ROOT / "tools" / "explore_demo.py"), "--headless", "--steps", str(a.steps),
                   "--maps", str(own), "--seed", str(1000 + i), "--starter", starter, "--control-port", str(8800 + i),
                   "--explore-rate", "0.5" if i % 2 else "0.0"]
            log = (swarm_dir / f"agent{i}.log").open("w")
            procs.append((i, subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)))
            print(f"agent {i}: starter {starter}, {'explorer' if i % 2 else 'exploiter'}, port {8800 + i}")
        t0 = time.time()
        for i, p in procs:
            rc = p.wait()
            print(f"agent {i} finished rc={rc} after {time.time() - t0:.0f}s")

    dst = json.loads(shared.read_text()) if shared.exists() else {"maps": {}}
    merged = 0
    for own in sorted(swarm_dir.glob("agent*.json")):
        try:
            merge_memory(dst, json.loads(own.read_text())); merged += 1
        except Exception as e:
            print(f"skip {own.name}: {e!r}")
    tmp = shared.with_suffix(".json.tmp"); tmp.write_text(json.dumps(dst, indent=1)); tmp.replace(shared)
    print(f"merged {merged} agent memories into {shared}: maps={len(dst['maps'])}, "
          f"tiles={sum(len(m['visited']) for m in dst['maps'].values())}, "
          f"interactions={sum(len(m.get('interactions', {})) for m in dst['maps'].values())}, "
          f"demos={sum(len(m.get('demos', [])) for m in dst['maps'].values())}")
    ms = ROOT / "runs" / "milestones.json"
    if ms.exists():
        hist = json.loads(ms.read_text())
        print("goal firsts (best step so far):", {g: min(e["step"] for e in v) for g, v in hist.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
