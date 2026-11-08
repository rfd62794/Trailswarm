"""Segment scorecard grades: per-segment health flags the scheduler and the review CLI steer by.

Pure over the stats dicts of runs/segments.json (seg_store). ``grade_all`` lazily imports seg_store
(tools/) so this module stays inside the package; callers arrange the path. Every threshold below is
an untuned first value. Grades never guess: a field an old attempt lacks reads as unknown (None or a
flag off), not invented.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

OPT_TOL = 0.15            # optimized: confirmed best within 15% of par (untuned first value)
PLATEAU_ATTEMPTS = 10     # no-par fallback: this many solved attempts since the best... (untuned)
PLATEAU_GAIN = 0.01       # ...that did not beat it by more than this fraction (untuned)
STALE_DAYS = 3            # no attempt for this long = stale (untuned)
BROKEN_MIN_AFTER = 5      # attempts with the newest git_sha needed before calling broken (untuned)
BROKEN_DROP = 0.40        # solve rate must fall by this much versus before that sha (untuned)
BROKEN_MIN_BEFORE = 0.70  # ...and have been at least this high before (untuned)
BROKEN_RECHECK_HOURS = 6  # at most one regression replay / repro job per segment this often (untuned)
POLISH_MIN = 0.05         # polish share when nothing needs polish (untuned)
POLISH_MAX = 0.35         # polish share ceiling (untuned)
POLISH_RAMP = 5           # +1/N of base polish per unoptimized solved segment (untuned)
EXPLORE_MIN = 0.0         # frontier-health explore floor: a healthy frontier exploits (untuned)
EXPLORE_MAX = 0.6         # ...and a sick one scouts (untuned)
REJOIN_SHARE = 0.05       # share of slots offered to rejoin probes while the pieces qualify (untuned)

_RUN_NAME = re.compile(r"explore-(\d{8})-(\d{6})-(\d+)")


def run_ts(name: str) -> float | None:
    """Epoch seconds (local time) of an ``explore-YYYYMMDD-HHMMSS-<pid>`` run-dir name, else None."""
    m = _RUN_NAME.match(str(name))
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
    except (ValueError, OverflowError, OSError):
        return None


@dataclass(frozen=True)
class Grade:
    key: str
    solved: bool
    optimized: bool
    stale: bool
    broken: bool
    held: str | None               # the hold reason, else None
    rate: float | None
    attempts: int                  # lifetime attempts (stats "n")
    best: int | None
    expected: float | None
    par: float | None
    health: float | None           # best / expected; None without both
    blackout_rate: float | None
    stall_rate: float | None
    loop_rate: float | None
    start: str                     # "ok" | ss.refusal reason | "missing" | "n/a" (the lineage seam)
    provenance: str                # "organic" | "synthetic" | "mixed" | "unknown"
    synthetic_only: bool           # solves exist but none is organic: a hypothesis, not a result
    last_ts: float | None
    sha_before: float | None       # solve rate before the newest git_sha (None: not computable)
    sha_after: float | None        # solve rate with the newest git_sha


def _mean_flag(attempts: list[dict], field: str) -> float | None:
    """Mean of ``bool(value)`` over the attempts; None when any lacks a usable value."""
    if not attempts:
        return None
    vals = []
    for a in attempts:
        v = a.get(field)
        if v is None:
            return None
        vals.append(bool(v))
    return sum(vals) / len(vals)


def _solved_only(st) -> bool:
    """True when the segment has solves (or an accepted best) and NONE of them is organic - a
    hypothesis, not a result. Requires real lineage evidence: attempts that predate the provenance
    field are ``unknown``, which is not organic but cannot indict the segment either. A recorded
    best/confirmed counts as organic evidence (only organic starts ever produce one)."""
    import seg_store as ss
    solvers = [a for a in ss.window(st) if a["solved"]]
    if not solvers and ss.accepted(st) is None:
        return False
    provs = [a.get("provenance") for a in solvers]
    if not any(p in ("organic", "synthetic", "promoted") for p in provs):
        return False                          # no lineage evidence at all: unknown, not synthetic-only
    if any(p == "organic" for p in provs) or st["confirmed"] or st["best"]:
        return False
    return True


def _provenance(st) -> str:
    """organic = every window solve started organically; synthetic = none did; mixed otherwise;
    unknown when there is nothing to judge or no lineage is recorded."""
    import seg_store as ss
    solvers = [a for a in ss.window(st) if a["solved"]]
    if not solvers:
        return "unknown"
    provs = [str(a.get("provenance") or "unknown") for a in solvers]
    if all(p == "organic" for p in provs):
        return "organic"
    if all(p != "organic" for p in provs):
        return "synthetic" if "synthetic" in provs else "unknown"
    return "mixed"


def _broken(st) -> tuple[bool, float | None, float | None]:
    """(broken, rate-before, rate-after) splitting the window at the newest git_sha."""
    import seg_store as ss
    w = ss.window(st)
    newest = next((a["git_sha"] for a in reversed(w) if a.get("git_sha")), None)
    if newest is None:
        return False, None, None
    first = next(i for i, a in enumerate(w) if a.get("git_sha") == newest)
    before, after = w[:first], [a for a in w if a.get("git_sha") == newest]
    if len(before) < BROKEN_MIN_AFTER or len(after) < BROKEN_MIN_AFTER:
        return False, None, None
    rb = sum(1 for a in before if a["solved"]) / len(before)
    ra = sum(1 for a in after if a["solved"]) / len(after)
    return rb >= BROKEN_MIN_BEFORE and ra <= rb - BROKEN_DROP, rb, ra


def _plateau_optimized(st, w: list[dict], best: dict) -> bool:
    """No-par fallback: at least PLATEAU_ATTEMPTS solves since the confirmed best was set, none
    beating it by more than PLATEAU_GAIN. The best's own attempt may have aged out of the window -
    then every window attempt counts."""
    b = best["frames"]
    idx = next((i for i in range(len(w) - 1, -1, -1)
                if w[i]["solved"] and w[i].get("run") == best.get("run") and w[i]["frames"] == b), None)
    since = w[idx + 1:] if idx is not None else w
    solvers = [a for a in since if a["solved"]]
    return len(solvers) >= PLATEAU_ATTEMPTS and all(a["frames"] >= b * (1 - PLATEAU_GAIN) for a in solvers)


def grade_segment(seg, st: dict, per_step: float, par: float | None, now: float,
                  hold: str | None = None, start: str = "n/a") -> Grade:
    import seg_store as ss
    w = ss.window(st)
    solved = ss.is_solved(st)
    syn = _solved_only(st)
    conf = st["confirmed"]
    if solved and conf is not None and not syn:
        optimized = (conf["frames"] <= par * (1 + OPT_TOL)) if par is not None else _plateau_optimized(st, w, conf)
    else:
        optimized = False
    last_ts = max((t for a in w if (t := a.get("ts") or run_ts(a.get("run", ""))) is not None), default=None)
    stale = last_ts is None or now - last_ts > STALE_DAYS * 86400
    broken, sha_b, sha_a = _broken(st)
    best = ss.best_frames(st)
    expected = ss.expected_frames(st, per_step)
    return Grade(
        key=seg.key, solved=solved, optimized=optimized, stale=stale, broken=broken, held=hold,
        rate=ss.rate(st), attempts=st["n"], best=best, expected=expected, par=par,
        health=(best / expected if best is not None and expected else None),
        blackout_rate=_mean_flag(w, "blackouts"), stall_rate=_mean_flag(w, "stalled"),
        loop_rate=_mean_flag(w, "loops"),
        start=start, provenance=_provenance(st), synthetic_only=syn,
        last_ts=last_ts, sha_before=sha_b, sha_after=sha_a)


def start_grade(root, seg) -> str:
    """The lineage seam: 'ok' | the checkpoint refusal reason | 'missing' | 'n/a' (no ledger)."""
    try:
        from pokeagent import statefp, statelog  # noqa: F401
        import seg_store as ss
    except ImportError:
        return "n/a"
    try:
        if ss.ckpt(Path(root), seg.start) is None:
            return "missing"
        return ss.refusal(Path(root), seg.start) or "ok"
    except Exception:  # noqa: BLE001 - a broken fingerprint must not take the scorecard down
        return "n/a"


def grade_all(doc: dict, root, now: float, par_fn=None, hold_file=None) -> list[Grade]:
    """One Grade per ``ss.layout(doc)`` segment, in chain order. ``par_fn(seg, st) -> float|None``."""
    import seg_store as ss
    from datetime import datetime
    holds = []
    if hold_file is not None:
        now_dt = datetime.fromtimestamp(now).astimezone()
        holds = [h for h in hold_file.current() if h.until > now_dt]
    per = ss.fps(doc)
    out = []
    for seg in ss.layout(doc):
        st = ss.stat(doc, seg.key)
        hold = next((h.reason for h in holds if h.covers(seg.key)), None)
        par = None
        if par_fn is not None:
            try:
                par = par_fn(seg, st)
            except Exception:  # noqa: BLE001 - a par we cannot compute is None, never a crash
                par = None
        out.append(grade_segment(seg, st, per, par, now, hold=hold, start=start_grade(root, seg)))
    return out


# --- allocation -----------------------------------------------------------------------------------------------
def grade_signal(g: Grade) -> bool:
    """True when any NEW column carries real data: a parseable attempt time/run name, a git_sha split,
    an event rate, or recorded provenance. Attempts that predate every new field grade all-unknown and
    must leave scheduling identical to the static shares."""
    return (g.last_ts is not None or g.sha_before is not None or g.sha_after is not None or g.broken
            or g.blackout_rate is not None or g.stall_rate is not None or g.loop_rate is not None
            or g.provenance != "unknown")


def effective_shares(grades: list[Grade], base: dict | None = None) -> dict:
    """Slot shares from the grades. With no new grade data (every column unknown) the base shares are
    returned untouched, so scheduling is identical to the static SHARES. Polish scales with the count
    of ``solved and not optimized and not held and not broken`` segments; the difference is taken
    from / given to unsolved+frontier proportionally (the dict always sums to 1)."""
    base = dict(base or {"unsolved": 0.40, "frontier": 0.45, "polish": 0.15})
    if not any(grade_signal(g) for g in grades):
        return base
    n_unopt = sum(1 for g in grades
                  if g.solved and not g.optimized and not g.held and not g.broken and not g.synthetic_only)
    polish = POLISH_MIN if n_unopt == 0 else min(POLISH_MAX, base["polish"] * (1 + n_unopt / POLISH_RAMP))
    rest = base["unsolved"] + base["frontier"]
    scale = (1.0 - polish) / rest if rest else 0.0
    return {"unsolved": base["unsolved"] * scale, "frontier": base["frontier"] * scale, "polish": polish}


def frontier_health(grade: Grade | None) -> float:
    """The frontier segment's health: its health column, else its window rate, else 0.5 (unknown)."""
    if grade is None:
        return 0.5
    if grade.health is not None:
        return grade.health
    return grade.rate if grade.rate is not None else 0.5


def explore_for_health(fh: float) -> float:
    """explore_rate for unsolved/frontier jobs: a sick frontier scouts, a healthy one exploits."""
    return EXPLORE_MIN + (EXPLORE_MAX - EXPLORE_MIN) * (1.0 - fh)


def solved_effective(g: Grade) -> bool:
    """What the shares count as solved: a synthetic-only hypothesis is not a solve."""
    return g.solved and not g.synthetic_only


# --- par ------------------------------------------------------------------------------------------------------
def segment_par(maps_path: list[int], entries_exits: list, grids) -> float | None:
    """Exact par of a multi-map segment: ``map_par`` per map traversed plus FRAME_WALK for each
    leaving press (every map but the last). None when any leg is unknown or the grids are absent."""
    if grids is None or not maps_path or len(entries_exits) != len(maps_path):
        return None
    from pokeagent.legs.grid import FRAME_WALK
    from pokeagent.legs.par import map_par
    total, last = 0.0, len(maps_path) - 1
    for i, (m, ee) in enumerate(zip(maps_path, entries_exits)):
        if ee is None:
            return None
        r = map_par(grids, m, ee[0], ee[1])
        if r is None:
            return None
        total += r[0] + (FRAME_WALK if i < last else 0.0)
    return total


def _jl(path: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def entries_exits_for(run_dir: Path, maps_path: list[int]) -> list:
    """(entry tile, exit tile) per map of a run's path, from its transitions.jsonl: the first tile
    seen on each map and, for every map but the last, the tile stood on when the press into the next
    map was made; for the last map the run's final position (the goal tile, approximately)."""
    trans = _jl(Path(run_dir) / "transitions.jsonl")
    entries: dict[int, tuple] = {}
    for r in trans:
        to = r.get("to")
        if to and len(to) >= 3 and to[0] not in entries:
            entries[to[0]] = (to[1], to[2])
    out = []
    for i, m in enumerate(maps_path):
        ent = entries.get(m)
        ex = None
        if ent is not None:
            if i == len(maps_path) - 1:
                last = [r["to"] for r in trans if r.get("to") and len(r["to"]) >= 3 and r["to"][0] == m]
                ex = (last[-1][1], last[-1][2]) if last else None
            else:
                nxt = maps_path[i + 1]
                row = next((r for r in trans if r.get("from") and r.get("to")
                            and len(r["from"]) >= 3 and len(r["to"]) >= 3
                            and r["from"][0] == m and r["to"][0] == nxt), None)
                ex = (row["from"][1], row["from"][2]) if row else None
        out.append((ent, ex) if ent is not None and ex is not None else None)
    return out


def par_for_best(root, st: dict, grids) -> float | None:
    """Par for a segment's accepted best: its run's map path and entry/exit tiles. None when the run
    or any leg is unknown - never guessed."""
    import seg_store as ss
    b = ss.accepted(st)
    run = (b or {}).get("run")
    att = next((a for a in st["attempts"] if a.get("run") == run and a["solved"] and a.get("maps")), None)
    rd = Path(root) / "runs" / run if run else None
    if att is None or rd is None or not rd.is_dir():
        return None
    return segment_par(att["maps"], entries_exits_for(rd, att["maps"]), grids)


def make_par_fn(root, grids):
    """``par_fn(seg, st)`` for grade_all over the ROM grids (or whatever ``grids`` resolves to)."""
    def par_fn(seg, st):
        return par_for_best(root, st, grids)
    return par_fn
