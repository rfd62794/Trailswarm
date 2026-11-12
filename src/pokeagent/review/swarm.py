"""``pokeagent review swarm``: the cross-run roll-up over a runs/ directory, with the breaks
section the exit code depends on. Read-only; each run's files are read once and battles.jsonl
is streamed once per invocation.
"""
from __future__ import annotations

import importlib.util
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from pokeagent import stalls, statefp
from pokeagent.game.stores import store_path
from pokeagent.review.load import jsonl, load_json, run_start
from pokeagent.review.loops import BREAK_LOOP_ROWS, LONG_LOOP_ROWS, collapse_loops, find_loops

EST_FRAMES_PER_STEP = 10.5  # seg_store.FRAMES_PER_STEP restated: only used when seg_ingest cannot load


def parse_since(s: str, now: datetime | None = None) -> datetime:
    """``--since``/``--until`` values: ``Nm``/``Nh`` ago, ``HH:MM`` today (local), or ISO."""
    now = now or datetime.now()
    s = s.strip()
    m = re.fullmatch(r"(\d+)m", s)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.fullmatch(r"(\d+)h", s)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return datetime.fromisoformat(s)


def _seg_ingest():
    """tools/seg_ingest.py, imported lazily with tools/ on sys.path for the duration of the load.
    Its module level is pure imports (stdlib + pokeagent); None when it cannot load."""
    tools = Path(__file__).resolve().parents[3] / "tools"
    spec = importlib.util.spec_from_file_location("seg_ingest", tools / "seg_ingest.py")
    if spec is None or spec.loader is None:
        return None
    mod = sys.modules.get("seg_ingest")
    if mod is not None:
        return mod
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seg_ingest"] = mod
    added = str(tools) not in sys.path
    if added:
        sys.path.insert(0, str(tools))
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop("seg_ingest", None)
        return None
    finally:
        if added:
            try:
                sys.path.remove(str(tools))
            except ValueError:
                pass
    return mod


def _attempt(run: Path, meta: dict, stop: str, milestones: dict) -> dict:
    """Solve judgement exactly as ``seg_ingest.build_attempt``: goal_frames.jsonl first, else
    milestones.json (frames estimated, flagged ``est``). Falls back to the restated rule."""
    si = _seg_ingest()
    if si is not None:
        a = si.build_attempt(run, meta, stop, milestones)
        return {"solved": a["solved"], "frames": a["frames"], "steps": a["steps"], "est": a["est"]}
    gf = next((r for r in jsonl(run / "goal_frames.jsonl") if r.get("goal") == stop and not r.get("skipped")), None)
    est = False
    if gf is None and not (run / "goal_frames.jsonl").exists():
        ms = next((e for e in (milestones or {}).get(stop, []) if e["run"] == run.name and not e.get("skipped")), None)
        if ms:
            gf, est = {"step": ms["step"], "frame": round(ms["step"] * EST_FRAMES_PER_STEP)}, True
    return {"solved": gf is not None, "frames": gf["frame"] if gf else 0,
            "steps": gf["step"] if gf else len(jsonl(run / "transitions.jsonl")), "est": est}


def _invariants(runs_dir: Path) -> tuple[str, list, list]:
    """(status, ERROR findings, WARN findings); never raises - an unavailable checker is reported."""
    try:
        from pokeagent.invariants import runner as inv_runner
        findings = inv_runner.run_all(Path(runs_dir))
        return "ok", [f.to_json() for f in findings if f.level == "ERROR"], \
            [f.to_json() for f in findings if f.level == "WARN"]
    except Exception as e:  # noqa: BLE001 - a diagnostic must never take down the tool
        return f"unavailable: {e}", [], []


def _legality(runs_dir: Path, checkpoint_paths: list[Path]) -> tuple[str, list]:
    """The Legal_State_Verify seam: ``pokeagent.legality.check(emu, kb)`` per checkpoint when the
    module exists on this branch; otherwise the documented "unavailable" status, never an error."""
    try:
        from pokeagent import legality  # type: ignore[import-not-found]  # built on another branch
    except ImportError:
        return "unavailable (no pokeagent.legality on this branch)", []
    check = getattr(legality, "check", None)
    if not callable(check):
        return "unavailable (pokeagent.legality has no check)", []
    try:
        from pokeagent.invariants.runner import find_rom
        rom = find_rom(Path(runs_dir))
        if rom is None:
            return "unavailable (no ROM beside runs/ for legality.check)", []
        kb = load_json(store_path("kb/rom_tables.json", root=Path(runs_dir).parent)) or None
        from pokeagent.emulator import PyBoyEmulator
        emu = PyBoyEmulator(rom, headless=True)
        violations: list[str] = []
        try:
            emu.tick(60)
            for st in checkpoint_paths:
                emu.load_state(st)
                res = check(emu, kb)
                violations += [f"{st.name}: {v}" for v in getattr(res, "violations", [])]
        finally:
            emu.close()
        return "ok", violations
    except Exception as e:  # noqa: BLE001
        return f"unavailable: {e}", []


def summarise(runs_dir: Path, since: datetime, until: datetime | None = None,
              segment: str | None = None, top: int = 5, invariants_verbose: bool = False) -> dict:
    """The swarm roll-up. ``broken`` is what the exit code depends on."""
    runs_dir = Path(runs_dir)
    skipped: dict = {}
    battles_by_run: dict[str, list] = defaultdict(list)
    for r in jsonl(runs_dir / "battles.jsonl", skipped):  # streamed once per invocation
        if r.get("run"):
            battles_by_run[r["run"]].append(r)
    milestones = load_json(runs_dir / "milestones.json")
    names, rows = set(), []
    for d in sorted(p for p in runs_dir.glob("explore-*") if p.is_dir()):
        # time first, from the dir name (no I/O); meta.json/mtime only for names that do not match
        t = run_start(d.name)
        if t is None:
            t = run_start(d.name, d)
        if t is None or t < since or (until is not None and t > until):
            continue
        meta = load_json(d / "meta.json")
        if not meta:
            continue
        stop = meta.get("stop_at_goal")
        if stop is None and meta.get("stop_at_map") is not None:
            stop = f"map:{meta['stop_at_map']:#04x}"   # same name seg_ingest._stop_name builds
        if segment and stop != segment:
            continue
        names.add(d.name)
        decisions = [r for r in jsonl(d / "decisions.jsonl", skipped) if "event" not in r]
        transitions = jsonl(d / "transitions.jsonl", skipped)
        sources = Counter(str(t2.get("source", "agent")) for t2 in transitions)
        rows.append({"dir": d, "name": d.name, "meta": meta, "t": t, "stop": stop,
                     "decisions": decisions, "transitions": transitions,
                     "watched": bool(meta.get("window")) or any(s != "agent" for s in sources),
                     "attempt": _attempt(d, meta, stop, milestones) if stop else None,
                     "episodes": find_loops(transitions, decisions),
                     "blackouts": sum(1 for b in battles_by_run.get(d.name, [])
                                    if b.get("outcome") == "blackout"),
                     "crashed": (d / "error.txt").exists() or (d / "crash.json").exists(),
                     "no_decisions": not decisions})
    # dossiers for the runs in range (stalls.load_dossiers takes the root containing runs/)
    root = runs_dir.parent if runs_dir.name == "runs" else runs_dir
    dossiers = [d for d in stalls.load_dossiers(root) if d.get("run") in names]
    if not dossiers and (runs_dir / "stalls").is_dir():  # runs_dir not literally named "runs"
        dossiers = [d for d in (load_json(p) for p in sorted((runs_dir / "stalls").glob("*.json")))
                    if d.get("signature") and d.get("run") in names]
    by_name = {r["name"]: r for r in rows}
    for d in dossiers:
        if d.get("run") in by_name:
            by_name[d["run"]]["dossier"] = d
    for r in rows:  # collapsed groups for the loops column; raw episodes stay for the breaks
        r["loops"] = collapse_loops(r["episodes"])
        r["long_loops"] = sum(1 for e in r["episodes"] if e["presses"] >= LONG_LOOP_ROWS)
    segments: dict[str, dict] = {}
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["stop"]:
            groups[r["stop"]].append(r)
    for seg, recs in sorted(groups.items()):
        attempts = [r["attempt"] for r in recs]
        solves = sum(1 for a in attempts if a["solved"])
        frames = [a["frames"] for a in attempts if a["solved"] and a["frames"]]
        segments[seg] = {"attempts": len(recs), "solves": solves,
                         "solve_rate": solves / len(recs),
                         "frames_best": min(frames) if frames else None,
                         "frames_median": statistics.median(frames) if frames else None,
                         "presses": sum(len(r["decisions"]) for r in recs),
                         "stall_rate": sum(1 for r in recs if r.get("dossier")) / len(recs),
                         "blackout_rate": sum(r["blackouts"] for r in recs) / len(recs),
                         "loop_episodes": sum(len(r["loops"]) for r in recs),
                         "long_loops": sum(r["long_loops"] for r in recs),
                         "failing": [r["name"] for r in recs if not r["attempt"]["solved"]]}
    clusters = stalls.cluster(dossiers)
    top_stalls = [{"cause": c["likely_cause"], "count": c["count"],
                   "signature_key": stalls.signature_key(c["signature"]),
                   "example": c["example_runs"][0] if c["example_runs"] else None}
                  for c in clusters[:top]]
    rule_counter: Counter = Counter()
    for r in rows:
        rule_counter.update(str(d.get("rule")) for d in r["decisions"])
    new_ckpts, ckpt_paths = [], []
    ck = runs_dir / "checkpoints"
    if ck.is_dir():
        for st in sorted(ck.glob("*.state")):
            try:
                mt = datetime.fromtimestamp(st.stat().st_mtime)
            except OSError:
                continue
            if mt < since or (until is not None and mt > until):
                continue
            ckpt_paths.append(st)
            fp = statefp.read(st) or {}
            new_ckpts.append({"state": st.name, "map": fp.get("map"), "badges": fp.get("badges"),
                              "party": [m[1] for m in fp.get("party") or [] if len(m) > 1],
                              "money": fp.get("money")})
    inv_status, inv_errors, inv_warns = _invariants(runs_dir)
    legality_status, legality_violations = _legality(runs_dir, ckpt_paths)
    crashed = [r["name"] for r in rows if r["crashed"]]
    no_decisions = [r["name"] for r in rows if r["no_decisions"]]
    loop_breaks = [{"run": r["name"], "kind": e["kind"], "step": e["step"], "presses": e["presses"]}
                   for r in rows for e in r["episodes"]
                   if e["kind"] in ("already_out", "blocked_loop") and e["presses"] >= BREAK_LOOP_ROWS]
    breaks = {"invariants": inv_status, "invariant_errors": inv_errors,
              "invariant_warns": inv_warns if invariants_verbose else len(inv_warns),
              "legality": legality_status, "legality_violations": legality_violations,
              "crashed": crashed, "no_decisions": no_decisions, "loop_breaks": loop_breaks}
    return {"runs_dir": str(runs_dir),
            "since": since.isoformat(timespec="seconds"),
            "until": until.isoformat(timespec="seconds") if until else None,
            "runs": {"count": len(rows), "segment_runs": sum(1 for r in rows if r["stop"]),
                     "watched": sum(1 for r in rows if r["watched"])},
            "segments": segments, "top_stall_causes": top_stalls,
            "top_rules": [{"rule": k, "presses": v} for k, v in rule_counter.most_common(top)],
            "new_checkpoints": new_ckpts, "breaks": breaks,
            "broken": bool(inv_errors or legality_violations or crashed or no_decisions or loop_breaks),
            "skipped_rows": skipped}
