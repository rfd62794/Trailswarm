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
        wc = d.setdefault("warp_cand", {})
        for k, n in s.get("warp_cand", {}).items():
            wc[k] = max(wc.get(k, 0), n)
        # Every agent started from a copy of the shared memory, so counts are taken as MAX, never summed:
        # summing would add the shared base once per agent and inflate solids, grades and counts.
        wt = d.setdefault("warp_taken", {})
        for k, n in s.get("warp_taken", {}).items():
            wt[k] = max(wt.get(k, 0), n)
        inter = d.setdefault("interactions", {})
        for k, e in s.get("interactions", {}).items():
            cur = inter.setdefault(k, {"count": 0, "text": "", "presses": [], "menus": [], "choices": []})
            cur["count"] = max(cur.get("count", 0), e.get("count", 0))
            if len(e.get("text", "")) > len(cur.get("text", "")):
                cur["text"] = e["text"]
            for key in ("presses", "menus", "choices", "effects"):
                for v in e.get(key, []) or []:
                    if v not in cur.setdefault(key, []):
                        cur[key].append(v)
            cur["presses"] = cur.get("presses", [])[-10:]
        demos = d.setdefault("demos", [])
        for dm in s.get("demos", []):
            if not dm.get("achieved"):
                continue  # only goal-achieving demonstrations are hypotheses worth keeping
            same = next((x for x in demos if x["at"] == dm["at"] and x["buttons"] == dm["buttons"]), None)
            if same:
                same["grade"] = min(same.get("grade", 0), dm.get("grade", 0))  # a bad grade anywhere sticks
                same["replays"] = max(same.get("replays", 0), dm.get("replays", 0))
            else:
                demos.append(dm)
        npcs = d.setdefault("npcs", {})
        for k, e in s.get("npcs", {}).items():
            cur = npcs.setdefault(k, {"pic": e["pic"], "slot": e["slot"], "positions": {}, "first_seen": e.get("first_seen", 0), "text": "", "talked": 0})
            for p, n in e.get("positions", {}).items():
                cur["positions"][p] = max(cur["positions"].get(p, 0), n)
            cur["moves"] = len(cur["positions"]) > 1
            cur["talked"] = max(cur.get("talked", 0), e.get("talked", 0))
            if len(e.get("text", "")) > len(cur.get("text", "")):
                cur["text"] = e["text"]
            cur["last"] = e.get("last", cur.get("last"))
        for key in ("encounters", "fails"):  # per-tile / per-edge counters: max, never summed (shared base)
            dd = d.setdefault(key, {})
            for k, n in s.get(key, {}).items():
                dd[k] = max(dd.get(k, 0), n)
        jm = d.setdefault("jumps", {})
        jm.update(s.get("jumps", {}))  # one-way ledge hops are facts: union
        d["last_seen"] = max(d.get("last_seen", 0), s.get("last_seen", 0))
    # --- everything else the agents learn goes into the collective knowledge too ---
    for key in ("move_damage", "enemy_damage", "damage_dealt", "damage_taken", "item_heal"):  # {key: [samples]}
        dd = dst.setdefault(key, {})
        for k, vals in src.get(key, {}).items():
            cur = dd.setdefault(k, [])
            if len(vals) > len(cur) and cur == vals[:len(cur)]:
                cur[:] = vals  # the agent extended the shared base: take its longer list, never re-append the base
            else:
                for v in vals:
                    if v not in cur:
                        cur.append(v)
            del cur[:-20]
    for key in ("items", "events", "catches"):  # append-only records: union by content, newest 300
        cur = dst.setdefault(key, [])
        for r in src.get(key, []):
            if r not in cur:
                cur.append(r)
        del cur[:-300]
    for sp, ls in src.get("battle_lessons", {}).items():  # per enemy species: fights/wins/fled are max (shared base)
        cur = dst.setdefault("battle_lessons", {}).setdefault(sp, {"fights": 0, "wins": 0, "fled": 0, "turns": [], "hp_lost": []})
        for f in ("fights", "wins", "fled"):
            cur[f] = max(cur.get(f, 0), ls.get(f, 0))
        for f in ("turns", "hp_lost"):
            cur[f] = (cur.get(f, []) + [v for v in ls.get(f, []) if v not in cur.get(f, [])])[-20:]
        if ls.get("best_move"):
            cur["best_move"] = ls["best_move"]; cur["move_avg_damage"] = ls.get("move_avg_damage", {})
    for name, rec in src.get("procedures", {}).items():  # verified menu procedures: keep the successes and the safest pace
        cur = dst.setdefault("procedures", {}).setdefault(name, {"ok": 0, "fail": 0, "pace": rec.get("pace", 12)})
        cur["ok"] = max(cur["ok"], rec.get("ok", 0)); cur["fail"] = max(cur["fail"], rec.get("fail", 0))
        if rec.get("ok", 0) >= cur["ok"]:
            cur["pace"] = rec.get("pace", cur["pace"])
    for mid, tr in src.get("training", {}).items():  # XP economics per map
        cur = dst.setdefault("training", {}).setdefault(mid, {"exp": 0, "steps": 0, "by_level": {}})
        cur["exp"] = max(cur["exp"], tr.get("exp", 0)); cur["steps"] = max(cur["steps"], tr.get("steps", 0))
        for lv, n in tr.get("by_level", {}).items():
            cur["by_level"][lv] = max(cur["by_level"].get(lv, 0), n)
    for k, v in src.get("menus", {}).items():
        dst.setdefault("menus", {}).setdefault(k, v)
    gi = dst.setdefault("grass_ids", {})
    for ts, table in src.get("grass_ids", {}).items():
        cur = gi.setdefault(ts, {})
        for k, n in table.items():
            cur[k] = max(cur.get(k, 0), n)
    dst["team_best_level"] = max(dst.get("team_best_level", 0), src.get("team_best_level", 0))
    bw = dst.setdefault("bad_warps", [])
    for ref in src.get("bad_warps", []):
        if ref not in bw:
            bw.append(ref)
    for ref in bw:  # tombstones win over any agent copy that still carries the pollution
        mid, sep, key = ref.partition(":")
        if sep:
            dst.get("maps", {}).get(mid, {}).get("warps", {}).pop(key, None)
    # whiteout respawns (Pokecenter door / home) are never doors from other maps (see explore_demo.WHITEOUT_LANDINGS)
    for mid, d in dst.get("maps", {}).items():
        for key, dest in list(d.get("warps", {}).items()):
            if tuple(dest) in {(1, 23, 26): 41, (0, 5, 6): 37} and int(mid) != {(1, 23, 26): 41, (0, 5, 6): 37}[tuple(dest)]:
                d["warps"].pop(key, None); d.get("warp_cand", {}).pop(key, None)
    beats = dst.setdefault("beats", {})
    for sig, b in src.get("beats", {}).items():
        cur = beats.get(sig)
        if cur is None or (b.get("grade", 0) >= 0 and (cur.get("grade", 0) < 0 or len(b["buttons"]) < len(cur["buttons"]))):
            beats[sig] = b
        elif cur is not None and b.get("grade", 0) < 0 and b["buttons"] == cur["buttons"]:
            cur["grade"] = min(cur.get("grade", 0), b["grade"])  # a failed replay anywhere lowers the shared grade
    tt = dst.setdefault("tile_types", {})
    for ts, table in src.get("tile_types", {}).items():
        t = tt.setdefault(ts, {})
        for k, e in table.items():
            cur = t.setdefault(k, {"solid": 0, "walkable": 0})
            cur["solid"] = max(cur["solid"], e.get("solid", 0)); cur["walkable"] = max(cur["walkable"], e.get("walkable", 0))
    dst["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--maps", default="runs/maps.json")
    ap.add_argument("--segment", default=None,
                    help="re-run ONE segment: agents start from runs/checkpoints/<previous goal>.state and stop at this goal")
    ap.add_argument("--roles", action="store_true",
                    help="specialised agents: half train from team_best.state (level up on Route 1), half explore from it (map expansion)")
    ap.add_argument("--starter", choices=["bulbasaur", "charmander", "squirtle"], default=None,
                    help="fix the starter for every agent (default: rotate bulbasaur/charmander/squirtle)")
    ap.add_argument("--share-frames", action="store_true",
                    help="agents publish rendered frames to shared memory for tools/watch.py (renders every Nth tick)")
    a = ap.parse_args()
    GOALS = ["potion", "left_house", "first_pokemon", "won_battle", "to_route1", "to_viridian", "oaks_parcel", "deliver_parcel", "to_route2", "to_pewter", "to_gym", "beat_brock"]
    seg_args: list[str] = []
    if a.segment:
        i = GOALS.index(a.segment)
        start = ROOT / "runs" / "checkpoints" / f"{GOALS[i - 1]}.state" if i > 0 else ROOT / "baselines" / "bedroom.state"
        if not start.exists():
            print(f"no checkpoint for the segment start: {start} (reach the previous goal in a run first)"); return 1
        seg_args = ["--state", str(start), "--stop-at-goal", a.segment]
        print(f"segment {a.segment}: starting every agent from {start.name}")
    shared = ROOT / a.maps
    swarm_dir = ROOT / "runs" / "swarm"; swarm_dir.mkdir(parents=True, exist_ok=True)

    if not a.merge_only:
        procs = []
        for i in range(a.agents):
            own = swarm_dir / f"agent{i}.json"
            if shared.exists():
                shutil.copy(shared, own)
            starter = a.starter or ["bulbasaur", "charmander", "squirtle"][i % 3]
            role_args: list[str] = []
            role = ""
            if a.roles:
                team = ROOT / "runs" / "checkpoints" / "team_best.state"
                start = team if team.exists() else ROOT / "runs" / "checkpoints" / "to_route1.state"
                if start.exists():
                    role = "trainer" if i % 2 == 0 else "explorer"
                    role_args = ["--state", str(start), "--explore-rate", "0.0" if role == "trainer" else "0.3"]
            cmd = [sys.executable, str(ROOT / "tools" / "explore_demo.py"), "--headless", "--steps", str(a.steps),
                   "--maps", str(own), "--seed", str(1000 + i), "--starter", starter, "--control-port", str(8800 + i),
                   "--box-pace", str([8, 16, 30][i % 3])] + (["--frame-share"] if a.share_frames else []) \
                   + (role_args or ["--explore-rate", "0.5" if i % 2 else "0.0"]) + seg_args
            if role:
                print(f"agent {i}: role {role}, starting from {Path(role_args[1]).name}")
            log = (swarm_dir / f"agent{i}.log").open("w")
            procs.append((i, subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)))
            print(f"agent {i}: starter {starter}, {'explorer' if i % 2 else 'exploiter'}, port {8800 + i}")
        t0 = time.time()
        deadline = t0 + max(240, a.steps * 1.2)  # ONE wall-clock budget for the whole round
        try:
            for i, p in procs:
                try:
                    rc = p.wait(timeout=max(1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    p.kill(); rc = "killed (timeout)"
                print(f"agent {i} finished rc={rc} after {time.time() - t0:.0f}s")
        finally:  # Ctrl+C or any error: never leave agents running (they hold ports 8800+i)
            for i, p in procs:
                if p.poll() is None:
                    p.kill()

    dst = json.loads(shared.read_text()) if shared.exists() else {"maps": {}}
    merged = 0
    for own in sorted(swarm_dir.glob("agent*.json")):
        try:
            merge_memory(dst, json.loads(own.read_text())); merged += 1
        except Exception as e:
            print(f"skip {own.name}: {e!r}")
    tmp = shared.with_suffix(".json.tmp"); tmp.write_text(json.dumps(dst, indent=1)); tmp.replace(shared)
    for own in swarm_dir.glob("agent*.json"):
        own.unlink()  # merged; a stale file must not be merged again by a later --merge-only
    print(f"merged {merged} agent memories into {shared}: maps={len(dst['maps'])}, "
          f"tiles={sum(len(m['visited']) for m in dst['maps'].values())}, "
          f"interactions={sum(len(m.get('interactions', {})) for m in dst['maps'].values())}, "
          f"demos={sum(len(m.get('demos', [])) for m in dst['maps'].values())}")
    ms = ROOT / "runs" / "milestones.json"
    if ms.exists():
        try:
            hist = json.loads(ms.read_text())
            print("goal firsts (best step so far):", {g: min(e["step"] for e in v) for g, v in hist.items()})
        except json.JSONDecodeError as e:
            print(f"milestones.json unreadable: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
