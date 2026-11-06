"""Fold finished segment runs (runs/explore-*/) into the curriculum stats, and gate new bests behind a replay.

A run is a segment attempt when its meta.json has stop_at_goal / stop_at_map and was not watched. The job tag
("seg:<key>" or "confirm:<key>:<run>") names which segment it was; older runs without a tag count for their goal's
segment when they started at the previous goal's checkpoint. A solve that beats the best is only a CANDIDATE: it
becomes the accepted best (and writes <end>.best.state) when a re-run with the same seed and the same starting memory
solves again (record_confirm). Candidates that cannot be replayed (no kept memory snapshot) stay unconfirmed.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from pokeagent.goals import GOALS
from pokeagent.segment_names import BEST_SUFFIX
from seg_store import FRAMES_PER_STEP, KEEP_ATTEMPTS, input_path, layout, stat

ABORTED_BELOW = 0.9    # an unsolved run that used less of its step budget than this was cut short
CONFIRM_SLACK = 1.02   # the replay may be up to 2% slower and still count (it should be identical)


def _jl(path: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def _maps_seen(run: Path) -> list[int]:
    """Map ids in order of first entry (the start map first): the sub-milestones of a partial attempt."""
    seen: list[int] = []
    for r in _jl(run / "transitions.jsonl"):
        m = (r.get("to") or [None])[0]
        if m is not None and m not in seen:
            seen.append(m)
    return seen[:40]


def _resolve(doc: dict, meta: dict) -> tuple[str | None, str | None]:
    """(segment key, confirmed-run or None) for a run's meta, or (None, None) when it is not a segment attempt."""
    tag = meta.get("tag") or ""
    if tag.startswith("confirm:"):
        parts = tag.split(":")
        return parts[1], parts[2]
    if tag.startswith("seg:"):
        return tag.split(":")[1], None
    g = meta.get("stop_at_goal")
    if not g or meta.get("window") or g in doc["splits"]:  # a watched (windowed) run may play differently: no stats
        return None, None
    i = GOALS.index(g)
    want = GOALS[i - 1] if i else None
    return (g, None) if meta.get("start") in ((want,) if want else ("baseline", "bedroom")) else (None, None)


def build_attempt(run: Path, meta: dict, stop: str, milestones: dict | None = None) -> dict:
    """One attempt. Old runs have no goal_frames.jsonl: their solve comes from milestones.json with frames ESTIMATED
    (steps x FRAMES_PER_STEP) and flagged ``est`` - good for solve rates, never trusted as a best."""
    gf = next((r for r in _jl(run / "goal_frames.jsonl") if r["goal"] == stop), None)
    steps = len(_jl(run / "transitions.jsonl"))
    est = False
    if gf is None and not (run / "goal_frames.jsonl").exists():
        ms = next((e for e in (milestones or {}).get(stop, []) if e["run"] == run.name), None)
        if ms:
            gf, est = {"step": ms["step"], "frame": ms["step"] * FRAMES_PER_STEP}, True
    return {"run": run.name, "solved": gf is not None, "frames": gf["frame"] if gf else 0, "est": est,
            "steps": gf["step"] if gf else steps, "seed": meta.get("seed"), "starter": meta.get("starter"),
            "explore_rate": meta.get("explore_rate"), "box_pace": meta.get("box_pace"), "budget": meta.get("steps"), "maps": _maps_seen(run)}


def _stop_name(seg) -> str:
    return seg.stop_goal if seg.stop_goal else f"map:{seg.stop_map:#04x}"


def record_attempt(root: Path, doc: dict, seg, att: dict, run: Path, tag: str | None) -> None:
    st = stat(doc, seg.key)
    st["attempts"] = (st["attempts"] + [att])[-KEEP_ATTEMPTS:]
    st["n"] += 1
    st["solves"] += int(att["solved"])
    if not att["solved"] or att["est"]:
        return
    end = run / "end.state"
    ck = root / "runs" / "checkpoints"
    if end.exists() and not (ck / f"{seg.end}.state").exists():
        ck.mkdir(parents=True, exist_ok=True)
        shutil.copy(end, ck / f"{seg.end}.state")  # sub-segments get their start checkpoint from the first solve
    cur = st["best"]
    if cur is not None and att["frames"] >= cur["frames"]:
        return
    sd = root / "runs" / "segments" / "states"
    sd.mkdir(parents=True, exist_ok=True)
    cand = sd / f"{seg.key}.cand.state"
    has_state = end.exists()
    if has_state:
        shutil.copy(end, cand)
    inp = input_path(root, tag) if tag else None
    st["best"] = {**{k: att[k] for k in ("frames", "steps", "run", "seed", "starter", "explore_rate", "box_pace", "budget")},
                  "confirmed": False, "tries": 0, "rejected": False,
                  "state": str(cand) if has_state else None,
                  "input": str(inp) if inp and inp.exists() else None}


def record_confirm(root: Path, doc: dict, seg, cand_run: str, att: dict) -> str:
    st = stat(doc, seg.key)
    b = st["best"]
    if not b or b["run"] != cand_run:
        return "stale"
    if att["solved"] and att["frames"] <= b["frames"] * CONFIRM_SLACK:
        b["confirmed"] = True
        st["confirmed"] = dict(b)
        if b.get("state") and Path(b["state"]).exists():
            ck = root / "runs" / "checkpoints"; ck.mkdir(parents=True, exist_ok=True)
            shutil.copy(b["state"], ck / f"{seg.end}{BEST_SUFFIX}.state")
        if b.get("input"):
            Path(b["input"]).unlink(missing_ok=True)  # the replay is done: the kept memory snapshot is dead weight
        b["input"] = st["confirmed"]["input"] = None
        return "confirmed"
    b["rejected"] = True
    st["best"] = st["confirmed"]  # fall back to the last route that DID replay
    return "rejected"


def release_input(root: Path, doc: dict, tag: str | None) -> None:
    """Delete the kept starting-memory snapshot of a job unless a best still needs it for its replay."""
    if not tag:
        return
    p = input_path(root, tag)
    held = {s["best"].get("input") for s in doc["stats"].values() if s.get("best")}
    if str(p) not in held:
        p.unlink(missing_ok=True)


def _quiet(run: Path, quiet_s: float) -> bool:
    newest = max((p.stat().st_mtime for p in run.iterdir()), default=0.0)
    return quiet_s <= 0 or time.time() - newest >= quiet_s


def ingest(root: Path, doc: dict, finished_tags: set[str] = frozenset(), quiet_s: float = 30.0) -> int:
    """Scan runs/explore-* once each; returns how many attempts were folded in. A run is final when its job tag is in
    ``finished_tags`` (its process exited) or nothing in its folder changed for ``quiet_s`` (not a live agent's)."""
    segs = {s.key: s for s in layout(doc)}
    done = set(doc["ingested"])
    n = 0
    try:
        milestones = json.loads((root / "runs" / "milestones.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        milestones = {}
    runs = sorted((root / "runs").glob("explore-*"), key=lambda p: p.name)  # names start with the start time
    for run in runs:
        if run.name in done or not (run / "meta.json").exists():
            continue
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8") or "{}")
        if not (meta.get("stop_at_goal") or meta.get("stop_at_map") is not None):
            doc["ingested"].append(run.name); continue
        if not (run / "transitions.jsonl").exists():
            continue
        if meta.get("tag") not in finished_tags and not _quiet(run, quiet_s):
            continue
        key, confirm_of = _resolve(doc, meta)
        seg = segs.get(key or "")
        doc["ingested"].append(run.name)
        if seg is None:
            continue
        att = build_attempt(run, meta, _stop_name(seg), milestones)
        if not att["solved"] and att["budget"] and att["steps"] < ABORTED_BELOW * att["budget"]:
            release_input(root, doc, meta.get("tag"))
            continue  # killed or crashed before using its step budget: neither a solve nor a fair failure
        tag = meta.get("tag") or ""
        if confirm_of:
            record_confirm(root, doc, seg, confirm_of, att)
        else:
            record_attempt(root, doc, seg, att, run, tag)
            n += 1
        release_input(root, doc, tag)
    doc["ingested"] = doc["ingested"][-4000:]
    return n
