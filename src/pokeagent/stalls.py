"""Stall dossiers: everything needed to diagnose one swarm stall, built from a run's own files (pure, no emulator).

A dossier is ``runs/stalls/<run>.json``. Its ``signature`` clusters stalls that are the same bug:
(map, dominant behaviour, dominant rule, dominant button, dominant outcome, sprite_adjacent).
Reads run dirs read-only; the only thing ever written is ``<root>/runs/stalls/<run>.json``.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

TAIL = 60            # decisions kept verbatim in the dossier
WINDOW = 600         # presses the histogram and the dominants cover
LOOPS_ROWS = 5000    # loops.jsonl rows scanned for the top vetoed actions
SPRITE_RADIUS = 2
DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}


def _jsonl_tail(path: Path, n: int) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(rows) > 4 * n:
                    del rows[:-n]
    except OSError:
        return []
    return rows[-n:]


def _load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _dominant(rows: list[dict], key: str) -> str | None:
    c = Counter(str(r.get(key)) for r in rows if r.get(key) is not None)
    return c.most_common(1)[0][0] if c else None


def _share(rows: list[dict], key: str, value: str | None) -> float:
    return sum(1 for r in rows if str(r.get(key)) == value) / len(rows) if rows and value else 0.0


def sprites_near(run: str, pos, maps_doc: dict | None = None, anomalies: list[dict] | None = None) -> list[dict]:
    """Sprites within SPRITE_RADIUS tiles of pos, from what the logs recorded: the run's own anomaly rows (npc_at) and the
    learned NPC table of the maps file (NPCs at their last seen tile). Empty when nothing was recorded."""
    if not pos or len(pos) < 3 or None in pos:
        return []
    m, x, y = pos[0], pos[1], pos[2]
    out: dict[tuple, dict] = {}

    def add(sx, sy, src, **extra):
        d = abs(sx - x) + abs(sy - y)
        if max(abs(sx - x), abs(sy - y)) <= SPRITE_RADIUS and (sx, sy) != (x, y):
            out[(sx, sy)] = {"x": sx, "y": sy, "dist": d, "adjacent": d == 1, "source": src, **extra}

    for a in anomalies or []:
        det = a.get("details") or {}
        if a.get("run") == run and a.get("map") == m and isinstance(det.get("npc_at"), list) and len(det["npc_at"]) == 2:
            add(det["npc_at"][0], det["npc_at"][1], "anomaly", pic=det.get("npc_pic"), slot=det.get("npc_slot"))
    for key, e in ((maps_doc or {}).get("maps", {}).get(str(m), {}).get("npcs") or {}).items():
        last = e.get("last")
        if isinstance(last, list) and len(last) == 2:
            add(last[0], last[1], "maps.npcs", npc=key, pic=e.get("pic"))
    return sorted(out.values(), key=lambda s: (s["dist"], s["x"], s["y"]))


def start_state_info(root: Path, meta: dict) -> dict:
    """The start state the run used: its segment input dir (state + maps copy) if still on disk, else its checkpoint."""
    tag = str(meta.get("tag") or "")
    info: dict = {"state": meta.get("state"), "tag": tag or None, "stop_at_goal": meta.get("stop_at_goal"),
                  "stop_at_map": meta.get("stop_at_map"), "inputs_dir": None, "state_file": None, "maps_copy": None}
    if tag.startswith("seg:"):
        d = root / "runs" / "segments" / "inputs" / ("seg_" + tag[4:].replace(":", "_"))
        if d.is_dir():
            info["inputs_dir"] = str(d)
            states = sorted(d.glob("*.state"))
            if states:
                info["state_file"] = str(states[0])
            if (d / "maps.json").exists():
                info["maps_copy"] = str(d / "maps.json")
    if info["state_file"] is None and meta.get("state"):
        for cand in (root / "runs" / "checkpoints" / f"{meta['state']}.state", root / "baselines" / f"{meta['state']}.state"):
            if cand.exists():
                info["state_file"] = str(cand)
                break
    return info


def segment_of(meta: dict) -> str | None:
    m = re.match(r"seg:([^:]+)", str(meta.get("tag") or ""))
    return m.group(1) if m else None


def make_signature(map_id, behaviour, rule, button, outcome, sprite_adjacent: bool) -> dict:
    return {"map": map_id, "behaviour": behaviour, "rule": rule, "button": button, "outcome": outcome,
            "sprite_adjacent": bool(sprite_adjacent)}


def signature_key(sig: dict) -> str:
    return "|".join(str(sig.get(k)) for k in ("map", "behaviour", "rule", "button", "outcome", "sprite_adjacent"))


def likely_cause(sig: dict, outcomes: dict, text: str, textbox: str, reversal_share: float = 0.0, tiles: int = 99) -> str:
    """One-line heuristic; first matching rule wins."""
    n = sum(outcomes.values()) or 1
    blocked = outcomes.get("blocked", 0) / n
    btn = sig.get("button")
    if sig.get("sprite_adjacent") and sig.get("outcome") == "blocked" and btn in DIRS:
        return "pressing into a sprite: person-not-wall class"
    if btn in ("A", "B") and ((textbox and textbox != "none") or text):
        return "A-mash in a text box"
    if "menu" in str(sig.get("rule")) or "menu" in str(sig.get("behaviour")):
        return "menu loop"
    if sig.get("behaviour") == "battle" or str(sig.get("rule")).startswith("battle"):
        return "battle loop"
    if btn in DIRS and sig.get("outcome") == "blocked" and blocked > 0.5:
        return "blocked by a learned wall the planner keeps targeting"
    if reversal_share > 0.4:
        return "oscillating between two targets (reversal loop)"
    if "shake" in str(sig.get("rule")):
        return "shake_walk wiggle: a guard fired and nothing resolved the block"
    if sig.get("outcome") == "moved" and tiles <= 12:
        return f"wandering inside {tiles} tiles: no target reached (planner target unreachable or already learned)"
    return "unclassified: read the decisions tail"


def top_vetoed(rows: list[dict], n: int = 5) -> list[dict]:
    """The n most frequent vetoed (situation, button) groups from a run's loops.jsonl rows (veto +
    veto_exhausted events). Each entry: {map, x, y, facing, button, rule, count}."""
    groups: dict[tuple, dict] = {}
    for r in rows:
        if r.get("kind") not in ("veto", "veto_exhausted"):
            continue
        key = (r.get("map"), r.get("x"), r.get("y"), r.get("facing"), r.get("text"), r.get("button"))
        g = groups.setdefault(key, {"map": key[0], "x": key[1], "y": key[2], "facing": key[3],
                                    "button": key[5], "rule": r.get("rule"), "count": 0})
        g["count"] += 1
    return sorted(groups.values(), key=lambda g: -g["count"])[:n]


def build_dossier(root: Path, run: str, stall: dict | None = None, maps_doc: dict | None = None,
                  anomalies: list[dict] | None = None, rdir: Path | None = None) -> dict | None:
    """Dossier for ``root/runs/<run>`` (or ``rdir``) or None when the run has no decisions. ``stall`` is the stalls.jsonl row."""
    rdir = rdir or root / "runs" / run
    win = _jsonl_tail(rdir / "decisions.jsonl", WINDOW)
    if not win:
        return None
    meta = _load(rdir / "meta.json")
    last = win[-1]
    pos = (stall or {}).get("pos") or [last.get("map"), last.get("x"), last.get("y")]
    beh, rule = _dominant(win, "behaviour"), _dominant(win, "rule")
    btn, out = _dominant(win, "button"), _dominant(win, "outcome")
    trans = _jsonl_tail(rdir / "transitions.jsonl", 40)
    texts: list[str] = []
    for t in trans:
        s = (t.get("text") or "").strip()
        if s and s not in texts:
            texts.append(s)
    textbox = trans[-1].get("textbox", "none") if trans else "none"
    if maps_doc is None:
        maps_doc = _load(rdir / "maps.json") or _load(root / "runs" / "maps.json")
    if anomalies is None:
        anomalies = [r for r in _jsonl_tail(root / "runs" / "anomalies.jsonl", 5000) if r.get("run") == run]
    sprites = sprites_near(run, pos, maps_doc, anomalies)
    sig = make_signature(pos[0], beh, rule, btn, out, any(s["adjacent"] for s in sprites))
    buttons, outcomes = dict(Counter(r.get("button") for r in win)), dict(Counter(r.get("outcome") for r in win))
    rev = sum(1 for r in win if r.get("reversal")) / len(win)
    tiles = len({(r.get("map"), r.get("x"), r.get("y")) for r in win})
    loops_rows = _jsonl_tail(rdir / "loops.jsonl", LOOPS_ROWS)
    prog_rows = _jsonl_tail(rdir / "progress.jsonl", 1)
    return {
        "run": run, "t": (stall or {}).get("t"), "slot": (stall or {}).get("slot"),
        "reason": (stall or {}).get("reason"), "presses": (stall or {}).get("presses") or last.get("step"),
        "map": pos[0], "x": pos[1], "y": pos[2],
        "segment": segment_of(meta), "seed": (stall or {}).get("seed", meta.get("seed")), "starter": meta.get("starter"),
        "goal_stage": last.get("goal_stage"),
        "signature": sig, "signature_key": signature_key(sig),
        "dominant": {"behaviour": beh, "rule": rule, "button": btn, "outcome": out,
                     "rule_share": round(_share(win, "rule", rule), 2), "tiles_in_window": tiles, "reversal_share": round(rev, 2)},
        "histogram": {"window": len(win), "buttons": buttons, "outcomes": outcomes,
                      "button_outcome": dict(Counter(f"{r.get('button')}:{r.get('outcome')}" for r in win))},
        "text_on_screen": {"textbox": textbox, "recent": texts[-5:]},
        "sprites_near": sprites,
        "start_state": start_state_info(root, meta),
        "likely_cause": likely_cause(sig, outcomes, texts[-1] if texts else "", textbox, rev, tiles),
        "top_vetoed": top_vetoed(loops_rows),
        "since_progress": prog_rows[-1].get("since") if prog_rows else None,
        "decisions_tail": win[-TAIL:],
    }


def write_dossier(root: Path, run: str, stall: dict | None = None, **kw) -> Path | None:
    d = build_dossier(root, run, stall, **kw)
    if d is None:
        return None
    out = root / "runs" / "stalls" / f"{run}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(out)
    return out


def safe_write_for_stall(root, run, stall: dict | None = None) -> Path | None:
    """The supervisor hook: write the dossier, never raise."""
    try:
        if not run:
            return None
        return write_dossier(Path(root), str(run), stall)
    except Exception:  # noqa: BLE001 - a diagnostic must never take down the supervisor
        return None


def load_dossiers(root: Path) -> list[dict]:
    out = []
    for p in sorted((root / "runs" / "stalls").glob("*.json")):
        d = _load(p)
        if d.get("signature"):
            out.append(d)
    return out


def coarse_key(d: dict) -> str:
    sg = d["signature"]
    return f"{sg['map']}|{sg['behaviour']}|{sg['rule']}"


def cluster(dossiers: list[dict], since_t: str | None = None, segment: str | None = None, examples: int = 3,
            coarse: bool = False) -> list[dict]:
    """Group dossiers by signature_key (or, coarse, by map|behaviour|rule), biggest first."""
    groups: dict[str, list[dict]] = {}
    for d in dossiers:
        if segment and d.get("segment") != segment:
            continue
        if since_t and (d.get("t") or "") < since_t:
            continue
        groups.setdefault(coarse_key(d) if coarse else d["signature_key"], []).append(d)
    rows = []
    for ds in groups.values():
        pos = Counter((d["map"], d["x"], d["y"]) for d in ds)
        rows.append({"count": len(ds), "signature": ds[0]["signature"], "likely_cause": ds[0]["likely_cause"],
                     "signatures": len({d["signature_key"] for d in ds}),
                     "segments": dict(Counter(d.get("segment") for d in ds)),
                     "positions": [list(p) for p, _ in pos.most_common(5)],
                     "example_runs": [d["run"] for d in sorted(ds, key=lambda d: d.get("t") or "", reverse=True)[:examples]]})
    return sorted(rows, key=lambda r: -r["count"])


def backfill(root: Path, stalls_path: Path | None = None) -> dict:
    """Dossiers for every row of runs/swarm/stalls.jsonl whose run dir still exists (existing dossiers are kept)."""
    sp = stalls_path or root / "runs" / "swarm" / "stalls.jsonl"
    rows = []
    try:
        with open(sp, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    maps_doc = _load(root / "runs" / "maps.json")
    by_run: dict = {}
    for a in _jsonl_tail(root / "runs" / "anomalies.jsonl", 20000):
        by_run.setdefault(a.get("run"), []).append(a)
    stats = {"rows": len(rows), "written": 0, "existing": 0, "no_run": 0, "no_decisions": 0}
    for r in rows:
        run = r.get("run")
        if not run or not (root / "runs" / run).is_dir():
            stats["no_run"] += 1
            continue
        if (root / "runs" / "stalls" / f"{run}.json").exists():
            stats["existing"] += 1
            continue
        if write_dossier(root, run, r, maps_doc=maps_doc, anomalies=by_run.get(run, [])):
            stats["written"] += 1
        else:
            stats["no_decisions"] += 1
    return stats
