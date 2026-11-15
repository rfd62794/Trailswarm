"""runs/states/library.json: every checkpoint and leg state indexed by team build, verdict and metrics. Rebuilt
from the ``.fp.json`` sidecars only (no emulator, no RAM); retention ranks legs per (segment, build); nothing deleted."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pokeagent import campaign, checkpoint_goals, party_rules, statefp, team_fp
from pokeagent.goals import GOALS
from pokeagent.goexplore.store import atomic_write
from pokeagent.knowledge.kb import table
from pokeagent.segment_names import state_goal

LIBRARY = Path("runs/states/library.json")
VERSION, KEEP_LEGS = 1, 3
TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"


def read(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"v": VERSION, "built": None, "entries": []}


def _layout(root: Path) -> tuple[list, dict]:
    """(leaf segments, stats) from runs/segments.json via tools/seg_store; GOALS order when there is no doc."""
    try:
        sys.path.insert(0, str(TOOLS_DIR))
        import seg_store
        doc = seg_store.load(Path(root))
        return seg_store.layout(doc), doc.get("stats") or {}
    except Exception:  # noqa: BLE001  no tools dir / unreadable doc
        return [SimpleNamespace(key=g, goal=g, start=GOALS[i - 1] if i else "bedroom", end=g,
                                stop_goal=g, stop_map=None) for i, g in enumerate(GOALS)], {}


def _seg_maps(seg, cp_fps) -> set:
    """A segment's maps: goals' detector maps (a ``g@<map>`` end stops BEFORE that goal), stop_map, cp fp maps."""
    base, eg = state_goal(seg.start), seg.end.split("@", 1)[0]
    lo = GOALS.index(base) if base in GOALS else -1
    hi = (GOALS.index(eg) - ("@" in seg.end)) if eg in GOALS else len(GOALS) - 1
    maps = set()
    for g in GOALS[lo + 1:hi + 1]:
        det = (campaign.goal_spec(g) or {}).get("detector")
        if isinstance(det, dict):
            maps |= set(det.get("map") or []) | {m for v in det.values() if isinstance(v, dict)
                                                 for m in v.get("map") or []}
    maps |= {m for nm in (seg.start, seg.end) if (m := (cp_fps.get(nm) or {}).get("map")) is not None}
    return maps | ({seg.stop_map} if seg.stop_map is not None else set())


def _faints(root: Path, run) -> int | None:
    """Newly fainted members (hp 0 after, > 0 before) from the run's own battles.jsonl; null when absent."""
    p = root / "runs" / str(run) / "battles.jsonl"
    if not run or not p.is_file():
        return None
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return sum(sum(1 for i, a in enumerate(r.get("party_after") or ())
                   if isinstance(a, list) and len(a) > 3 and a[3] == 0 and i < len(b) and b[i][3] > 0)
               for r in rows if isinstance(r, dict) for b in [r.get("party_before") or []])


def _readiness(fp: dict, done: dict | None, kb) -> tuple:
    """(lead sim score, next boss) for the state's stage; nulls when the data cannot decide."""
    try:
        from pokeagent.explorer import training
        from pokeagent.knowledge import party, trainers
        from pokeagent.knowledge.readiness import team_readiness
        if done is None or (stage := training.stage_goal(done)) is None:
            return None, None
        names = table(kb, "name_of_internal")
        team = [m for m in fp.get("team") or () if isinstance(m, dict)]
        sp = [names.get(str(m.get("species")), "") for m in team]
        party_ = [c for n, m in zip(sp, team) if (c := party.trainer_mon(n, m.get("level") or 0, kb))]
        boss = trainers.boss_party(stage, kb, starter_names=[n for n in sp if n])
        boss = boss or (trainers.strongest_on_mt_moon(kb) if stage == "to_mt_moon" else [])
        if not party_ or not boss:
            return None, stage.split("beat_", 1)[-1]
        t = team_readiness(party_, boss, training.BOSS_LABEL[stage], kb)
        return (t.lead.score if t and t.lead else None), stage.split("beat_", 1)[-1]
    except Exception:  # noqa: BLE001
        return None, None


def _entry(tier: str, p: Path, fp: dict, root: Path, segment, segs_by_key, kb) -> dict:
    completed = checkpoint_goals.read_completed(p)
    if completed is not None:
        done = {g: True for g in completed}
    else:                                                               # infer from the segment's start
        seg = segs_by_key.get(segment)
        base = state_goal(seg.start) if seg else None
        done = None if seg is None else {g: True for g in GOALS[:(GOALS.index(base) + 1 if base in GOALS else 0)]}
    run = fp.get("source_run")
    try:
        seed = json.loads((root / "runs" / str(run) / "meta.json").read_text(encoding="utf-8")).get("seed")
    except (OSError, ValueError, TypeError):
        seed = None
    score, boss = _readiness(fp, done, kb)
    return {"tier": tier, "name": p.name[:-len(".state")], "segment": segment,
            "state": Path(os.path.relpath(p, root)).as_posix(), "build": team_fp.build_key(fp, kb),
            "team": [[m.get("species"), m.get("level"), sorted(team_fp.moves_of(m, kb))]
                     for m in fp.get("team") or () if isinstance(m, dict)],
            "verdict": party_rules.verdict(fp, kb), "violations": party_rules.violations(fp, kb),
            "run": run, "seed": seed, "parent": fp.get("parent"),
            "created": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "metrics": {"steps": fp.get("frames"), "faints": _faints(root, run),
                        "readiness": score, "readiness_boss": boss}}


def retain(entries: list, k: int = KEEP_LEGS) -> tuple[list, list]:
    """Best-K legs per (segment, build) by (clean, readiness, fewest steps, newest); checkpoints never drop."""
    def rank(e):
        r = (e.get("metrics") or {}).get("readiness")
        return (e.get("verdict") == "clean", r if isinstance(r, (int, float)) and not isinstance(r, bool) else -1,
                -((e.get("metrics") or {}).get("steps") or 10 ** 12), e.get("created") or "")
    groups: dict = {}
    for e in (x for x in entries if x.get("tier") == "leg"):
        groups.setdefault((e.get("segment"), e.get("build")), []).append(e)
    dropped = [e for g in groups.values() for e in sorted(g, key=rank, reverse=True)[k:]]
    return [e for e in entries if id(e) not in {id(x) for x in dropped}], dropped


def build(directories, *, root=".", out=LIBRARY, keep_legs=KEEP_LEGS, kb=None) -> tuple[dict, list]:
    """Scan the state dirs (runs/retired excluded) and write the index atomically. Returns (doc, dropped)."""
    root, segments = Path(root), _layout(Path(root))[0]
    scanned = [(("checkpoint" if d.name == "checkpoints" else "leg"), p, statefp.read(p) or {})
               for d in map(Path, directories) if d.name != "retired" and d.is_dir()
               for p in sorted(d.glob("*.state"), key=lambda x: x.name)]
    cp_fps = {p.name[:-len(".state")].removesuffix(".best"): fp for t, p, fp in scanned if t == "checkpoint"}
    starts, segs_by_key = {s.start: s.key for s in segments}, {s.key: s for s in segments}
    entries = []
    for tier, p, fp in scanned:
        stem = p.name[:-len(".state")].removesuffix(".best")
        hits = [] if tier == "checkpoint" or not isinstance(fp.get("map"), int) else \
            [s.key for s in segments if fp["map"] in _seg_maps(s, cp_fps)]   # unique match or null
        segment = starts.get(stem) if tier == "checkpoint" else hits[0] if len(hits) == 1 else None
        entries.append(_entry(tier, p, fp, root, segment, segs_by_key, kb))
    doc = {"v": VERSION, "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "entries": entries}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    atomic_write(Path(out), json.dumps(doc, indent=1))
    return doc, retain(entries, keep_legs)[1]
