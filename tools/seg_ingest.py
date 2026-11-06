"""Fold finished segment runs (runs/explore-*/) into the curriculum stats, and gate new bests behind a replay.

A run is a segment attempt when its meta.json has stop_at_goal / stop_at_map and was not watched. The job tag
("seg:<key>" or "confirm:<key>:<run>") names which segment it was; older runs without a tag count for their goal's
segment when they started at the previous goal's checkpoint. A solve that beats the best is only a CANDIDATE: it
becomes the accepted best (and writes <end>.best.state) when a re-run with the same seed and the same starting memory
solves again (record_confirm). The replay starts from the EXACT start-state file the candidate used (a copy kept under
runs/segments/inputs/<tag>/ with its sha256 and the map-memory snapshot), never from whatever checkpoint is current
by then. Candidates that cannot be replayed stay unconfirmed. A run with outside input (non-agent presses) is never a
candidate and an inconclusive replay is retried, not rejected. end.state is kept only for candidates.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from pokeagent.segment_names import BEST_SUFFIX
from seg_store import KEEP_ATTEMPTS, fps, input_path, job_dir, layout, remove_tree, stat

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
    seg = next((x for x in layout(doc) if x.key == g), None)   # None: not a selectable goal (never a segment target)
    if seg is None:
        return None, None
    return (g, None) if meta.get("start") in ((seg.start,) if seg.start != "bedroom" else ("baseline", "bedroom")) else (None, None)


def calibrate(doc: dict, run: Path) -> None:
    """Fold a run's goal_frames deltas (frames and presses between consecutive goals) into the frames-per-press estimate."""
    prev_s = prev_f = 0
    c = doc.setdefault("calib", {"frames": 0, "steps": 0})
    for r in _jl(run / "goal_frames.jsonl"):
        if r["step"] > prev_s and r["frame"] > prev_f:
            c["frames"] += r["frame"] - prev_f
            c["steps"] += r["step"] - prev_s
        prev_s, prev_f = r["step"], r["frame"]


def build_attempt(run: Path, meta: dict, stop: str, milestones: dict | None = None, per_step: float = 10.5) -> dict:
    """One attempt. Old runs have no goal_frames.jsonl: their solve comes from milestones.json with frames ESTIMATED
    (steps x calibrated frames per press) and flagged ``est`` - good for solve rates, never trusted as a best."""
    gf = next((r for r in _jl(run / "goal_frames.jsonl") if r["goal"] == stop), None)
    steps = len(_jl(run / "transitions.jsonl"))
    est = False
    if gf is None and not (run / "goal_frames.jsonl").exists():
        ms = next((e for e in (milestones or {}).get(stop, []) if e["run"] == run.name), None)
        if ms:
            gf, est = {"step": ms["step"], "frame": round(ms["step"] * per_step)}, True
    return {"run": run.name, "solved": gf is not None, "frames": gf["frame"] if gf else 0, "est": est,
            "steps": gf["step"] if gf else steps, "seed": meta.get("seed"), "starter": meta.get("starter"),
            "explore_rate": meta.get("explore_rate"), "box_pace": meta.get("box_pace"), "budget": meta.get("steps"), "maps": _maps_seen(run),
            "tagged": bool(meta.get("tag")), "outside": sum(1 for r in _jl(run / "transitions.jsonl") if r.get("source", "agent") != "agent")}


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
    if (cur is not None and att["frames"] >= cur["frames"]) or att["outside"]:
        return  # not faster, or someone else's presses were in it: not a route we can stand behind
    sd = root / "runs" / "segments" / "states"
    sd.mkdir(parents=True, exist_ok=True)
    cand = sd / f"{seg.key}.cand.state"
    has_state = end.exists()
    if has_state:
        shutil.copy(end, cand)
    inp = input_path(root, tag) if tag else None
    job = _job_record(root, tag)
    st["best"] = {**{k: att[k] for k in ("frames", "steps", "run", "seed", "starter", "explore_rate", "box_pace", "budget")},
                  "confirmed": False, "tries": 0, "rejected": False,
                  "state": str(cand) if has_state else None,
                  "input": str(inp) if inp and inp.exists() else None,
                  "start": job.get("start"), "start_sha": job.get("start_sha")}


def _job_record(root: Path, tag: str | None) -> dict:
    """{start, start_sha} of a normal job: the exact start-state copy and its sha256, written when the job launched."""
    try:
        d = job_dir(root, tag)
        rec = json.loads((d / "job.json").read_text(encoding="utf-8"))
        return {"start": str(d / rec["start_name"]), "start_sha": rec["start_sha"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def record_confirm(root: Path, doc: dict, seg, cand_run: str, att: dict) -> str:
    st = stat(doc, seg.key)
    b = st["best"]
    if not b or b["run"] != cand_run:
        return "stale"
    if att["outside"] or (not att["solved"] and att["budget"] and att["steps"] < ABORTED_BELOW * att["budget"]):
        b["tries"] = max(0, b["tries"] - 1)
        return "inconclusive"  # outside input or cut short: say nothing about the route, try the replay again
    if att["solved"] and att["frames"] <= b["frames"] * CONFIRM_SLACK:
        b["confirmed"] = True
        st["confirmed"] = dict(b)
        if b.get("state") and Path(b["state"]).exists():
            ck = root / "runs" / "checkpoints"; ck.mkdir(parents=True, exist_ok=True)
            shutil.copy(b["state"], ck / f"{seg.end}{BEST_SUFFIX}.state")
        drop_kept(root, b)  # the replay is done: the kept memory snapshot, start copy and candidate state are dead weight
        st["confirmed"] = dict(b)
        return "confirmed"
    b["rejected"] = True
    st["best"] = st["confirmed"]  # fall back to the last route that DID replay
    return "rejected"


def drop_kept(root: Path, b: dict, log=print) -> None:
    for k in ("input", "start", "state"):
        if b.get(k):
            if k == "state":
                Path(b[k]).unlink(missing_ok=True)
            else:
                remove_tree(root, Path(b[k]).parent, log)  # the job dir holds both
        b[k] = None


def release_input(root: Path, doc: dict, tag: str | None) -> None:
    """Delete the kept job dir (memory snapshot + start copy) unless a best still needs it for its replay."""
    if not tag:
        return
    d = job_dir(root, tag)
    held = {str(Path(s["best"]["input"]).parent) for s in doc["stats"].values() if s.get("best") and s["best"].get("input")}
    if str(d) not in held:
        remove_tree(root, d)


def _quiet(run: Path, quiet_s: float) -> bool:
    newest = max((p.stat().st_mtime for p in run.iterdir()), default=0.0)
    return quiet_s <= 0 or time.time() - newest >= quiet_s


def ingest(root: Path, doc: dict, finished_tags: set[str] = frozenset(), quiet_s: float = 30.0,
           failed_tags: set[str] = frozenset()) -> int:
    """Scan runs/explore-* once each; returns how many attempts were folded in. A run is final when its job tag is in
    ``finished_tags`` (its process exited) or nothing in its folder changed for ``quiet_s`` (not a live agent's).
    ``failed_tags`` are jobs the stall watchdog stopped: a real failure even though they used little of their budget."""
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
        calibrate(doc, run)
        att = build_attempt(run, meta, _stop_name(seg), milestones, fps(doc))
        if (not att["solved"] and not confirm_of and meta.get("tag") not in failed_tags
                and att["budget"] and att["steps"] < ABORTED_BELOW * att["budget"]):
            release_input(root, doc, meta.get("tag"))
            continue  # killed or crashed before using its step budget: neither a solve nor a fair failure
        tag = meta.get("tag") or ""
        if confirm_of:
            record_confirm(root, doc, seg, confirm_of, att)
        else:
            record_attempt(root, doc, seg, att, run, tag)
            n += 1
        release_input(root, doc, tag)
        (run / "end.state").unlink(missing_ok=True)  # kept only for candidates (record_attempt copied it)
    doc["ingested"] = doc["ingested"][-4000:]
    return n
