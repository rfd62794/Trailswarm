"""Folding one agent's memory into the shared runs/maps.json (merge rules, atomic write, merge lock).

Every agent starts from a copy of the shared memory, so counts are taken as MAX, never summed.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path


def merge_memory(dst: dict, src: dict, edits: list | None = None) -> dict:
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
        wd = d.setdefault("warp_disproof", {})
        for k, n in s.get("warp_disproof", {}).items():
            wd[k] = max(wd.get(k, 0), n)
        wdt = d.setdefault("warp_disproof_total", {})
        for k, n in s.get("warp_disproof_total", {}).items():
            wdt[k] = max(wdt.get(k, 0), n)
        for name in ("warp_disproof", "warp_disproof_total"):
            if not d[name]:
                del d[name]  # keep maps.json free of an empty key
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
            md = dst.get("maps", {}).get(mid, {})
            md.get("warps", {}).pop(key, None); md.get("warp_cand", {}).pop(key, None); md.get("warp_taken", {}).pop(key, None)
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
    if edits:  # brain-tools surgery: the journal is folded in AFTER merging so no agent copy can resurrect an edit
        from pokeagent.explorer.edits import apply as apply_edits
        apply_edits(dst, edits)
    return dst


_sleep = time.sleep


def replace_durably(tmp: Path, text: str, dest: Path, tries: int = 5) -> None:
    """Write tmp, fsync, then os.replace; a Windows reader holding dest open raises PermissionError, so back off."""
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    for i in range(tries):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if i == tries - 1:
                tmp.unlink(missing_ok=True)
                raise
            _sleep(0.1 * (i + 1))


@contextmanager
def merge_lock(shared: Path, wait_s: float = 30.0):
    """``<maps>.lock``: two finishes (or a --merge-only beside a live swarm) never read-modify-write at once."""
    from pokeagent import resources
    path = shared.with_suffix(".lock")
    end = time.monotonic() + wait_s
    while not resources._try_acquire(path):
        if resources._stale(path):
            resources._take_over(path)
        elif time.monotonic() >= end:
            raise resources.LockBusy(f"merge lock busy: {path}")
        else:
            time.sleep(0.05)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def merge_file_into(shared: Path, own: Path) -> dict:
    """Merge one agent memory file into ``shared`` under the merge lock, write atomically, return the result."""
    from pokeagent.explorer.edits import journal_path_for, read_journal
    with merge_lock(shared):
        dst = json.loads(shared.read_text()) if shared.exists() else {"maps": {}}
        merge_memory(dst, json.loads(own.read_text()), edits=read_journal(journal_path_for(shared)))
        tmp = shared.with_suffix(".json.tmp")
        replace_durably(tmp, json.dumps(dst, indent=1), shared)
    return dst
