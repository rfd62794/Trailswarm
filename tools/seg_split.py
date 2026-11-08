"""Auto-split: a segment that keeps failing is cut at natural sub-milestones (first entry into each new map id).

Trigger: >= MIN_ATTEMPTS attempts and a solve rate under SPLIT_RATE over the last window - OR (the long-solve
trigger) the median solve costs more than SPLIT_PAR_MULT x the ROM par. Cut points come only from TRUSTED partial
attempts (failed, tagged curriculum runs whose frames were not estimated): the map ids, in order of first entry,
along the failed attempt that got furthest. A cut map must (1) not be the segment's own start map, (2) not appear
in any earlier segment's attempts (it is part of the way TO this segment, not progress in it) and (3) be reached by
at least MIN_REACH of the trusted failed attempts. When more maps qualify than MAX_CUTS allows, the cuts are chosen
by EVENT support (a heal, trainer win, item or level gain just before entering them) so a cut lands after progress,
not arbitrarily. The pieces get their own checkpoints and stats and chain back together (seg_store.layout); the
original segment's history is kept but unused - except rejoin probes, whose ``rejoin``-tagged attempts the
should_rejoin check reads. reset() undoes a split.
"""
from __future__ import annotations

import json
from pathlib import Path

from seg_store import Segment, WINDOW, accepted, layout, rate, stat, window

MIN_ATTEMPTS = 20
SPLIT_RATE = 0.30
MAX_CUTS = 4
MIN_REACH = 2
SPLIT_PAR_MULT = 3.0      # long-solve trigger: median solve costs more than this x par (untuned first value)
MIN_SOLVES_FOR_LONG = 5   # ...with at least this many solves before trusting the median (untuned)
REJOIN_PROBES = 2         # consecutive probe solves within REJOIN_TOL of the pieces' sum needed to rejoin (untuned)
REJOIN_TOL = 0.10         # probe frames may differ from the pieces' accepted-best sum by this much (untuned)
EVENT_LOOKBACK = 200      # presses before a map entry in which a goal-relevant event supports cutting there (untuned)
HINT_SLACK = 5            # a cut this many presses around a map entry IS expressible as a map stop (untuned)
MAX_HINTS = 3             # cut_hints reported per segment (untuned)


def _jl(path: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def trusted_failures(attempts: list[dict]) -> list[dict]:
    return [a for a in attempts if not a["solved"] and a.get("maps") and a.get("tagged") and not a.get("est")]


def _entries(run_dir: Path) -> list[tuple[int, int]]:
    """(map_id, step) of every first map entry in a run, in order."""
    seen: set[int] = set()
    out = []
    for r in _jl(Path(run_dir) / "transitions.jsonl"):
        to = r.get("to")
        if to and len(to) >= 1 and to[0] not in seen:
            seen.add(to[0])
            out.append((to[0], r.get("step") or 0))
    return out


def _events(run_dir: Path) -> list[dict]:
    """Goal-relevant events with their step: a heal visit (entering a *_POKECENTER map), a trainer win,
    an item pickup (an 'item' rule press), a level gain (levels.jsonl). Best effort, never raises."""
    out = []
    for r in _jl(Path(run_dir) / "transitions.jsonl"):
        to, frm = r.get("to"), r.get("from")
        if to and len(to) >= 1 and frm and len(frm) >= 1 and _map_name(to[0]).endswith("_POKECENTER"):
            out.append({"step": r.get("step") or 0, "kind": "heal", "map": frm[0]})
    for b in _jl(run_dir.parent / "battles.jsonl"):
        if b.get("run") == run_dir.name and b.get("won") and b.get("trainer"):
            out.append({"step": b.get("end") or 0, "kind": "trainer_win", "map": b.get("battle_map")})
    for r in _jl(Path(run_dir) / "decisions.jsonl"):
        if "item" in str(r.get("rule")):
            out.append({"step": r.get("step") or 0, "kind": "item", "map": r.get("map")})
    prev = None
    from pokeagent.training_progress import gained, marks
    for r in _jl(Path(run_dir) / "levels.jsonl"):
        cur = marks(r.get("party"))
        if prev is not None and gained(prev, cur):
            out.append({"step": r.get("step") or 0, "kind": "level", "map": r.get("map")})
        prev = cur
    return out


def _map_name(map_id: int) -> str:
    try:
        names = _map_name._names
    except AttributeError:
        try:
            from pokeagent import atlas
            names = json.loads((Path(atlas.__file__).parent / "map_names.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            names = {}
        _map_name._names = names
    return names.get(str(map_id), "")


def event_support(run_dir, map_id: int) -> int:
    """Goal-relevant events (heal / trainer win / item / level gain) at or just before FIRST entering
    ``map_id`` in ``run_dir``: the events since the previous map's entry, capped at EVENT_LOOKBACK
    presses back. A cut after such an entry lands after progress, not mid-struggle."""
    entries = _entries(Path(run_dir))
    hit = next((s for m, s in entries if m == map_id), None)
    if hit is None:
        return 0
    prev = max((s for m, s in entries if s < hit), default=-1)
    lo = max(prev, hit - EVENT_LOOKBACK)
    return sum(1 for e in _events(Path(run_dir)) if lo < e["step"] <= hit)


def _ranked(cands: list[int], run_dirs: list[Path]) -> list[int]:
    """Choose up to MAX_CUTS of the candidate cut maps by total event support across the trusted runs
    (ties keep path order), then emit them in path order: the chain needs entries in travel order."""
    if len(cands) <= MAX_CUTS or not run_dirs:
        return cands[:MAX_CUTS]
    support = {m: sum(event_support(d, m) for d in run_dirs) for m in cands}
    pos = {m: i for i, m in enumerate(cands)}
    keep = sorted(cands, key=lambda m: (-support[m], pos[m]))[:MAX_CUTS]
    return sorted(keep, key=lambda m: pos[m])


def cut_maps(attempts: list[dict], earlier: set[int] = frozenset(), run_dirs: list | None = None) -> list[int]:
    failed = trusted_failures(attempts)
    if len(failed) < MIN_REACH:
        return []
    starts = {a["maps"][0] for a in failed}
    reach: dict[int, int] = {}
    for a in failed:
        for m in a["maps"][1:]:
            reach[m] = reach.get(m, 0) + 1
    best = max(failed, key=lambda a: len(a["maps"]))
    cands = [m for m in best["maps"][1:] if m not in starts and m not in earlier and reach.get(m, 0) >= MIN_REACH]
    return _ranked(cands, [Path(d) for d in run_dirs or []])


def cut_hints(st: dict, root) -> list[dict]:
    """Report-only: goal-relevant events in the trusted failed runs that a MAP stop cannot express
    (no map entry within HINT_SLACK presses): the spots a future stop-at-event condition would cut at."""
    out, seen = [], set()
    for a in trusted_failures(window(st)):
        rd = Path(root) / "runs" / a.get("run", "")
        if not rd.is_dir():
            continue
        marks = {s for _m, s in _entries(rd)}
        for e in _events(rd):
            key = (e["kind"], e.get("map"))
            if key in seen or any(abs(e["step"] - s) <= HINT_SLACK for s in marks):
                continue
            seen.add(key)
            out.append({"run": rd.name, "kind": e["kind"], "map": e.get("map"), "step": e["step"]})
            if len(out) >= MAX_HINTS:
                return out
    return out


def should_split(st: dict) -> bool:
    r = rate(st)
    if st["n"] < MIN_ATTEMPTS or len(window(st)) < WINDOW or r is None or r >= SPLIT_RATE:
        return False
    return st["n"] >= st.get("split_retry_at", 0)


def should_split_long(st: dict, par: float | None) -> bool:
    """The long-solve trigger: the median solve costs more than SPLIT_PAR_MULT x par. Skipped without
    a par (never guessed) and without MIN_SOLVES_FOR_LONG solves to trust the median."""
    if par is None or st["n"] < st.get("split_retry_at", 0):
        return False
    solves = sorted(a["frames"] for a in window(st) if a["solved"] and not a.get("est"))
    if len(solves) < MIN_SOLVES_FOR_LONG:
        return False
    return solves[len(solves) // 2] > SPLIT_PAR_MULT * par


def maybe_split(doc: dict, root=None, par_fn=None) -> list[str]:
    """Split every top-level segment that qualifies; returns the goals split. Unsplittable ones retry after WINDOW more.
    ``root`` + ``par_fn(seg, st)`` enable the long-solve trigger and the event-ranked cut choice."""
    done = []
    seen: set[int] = set()   # maps in the attempts of the segments before this one
    for seg in layout(doc):
        st = stat(doc, seg.key)
        if seg.key == seg.goal:
            par = par_fn(seg, st) if par_fn is not None else None
            if should_split(st) or should_split_long(st, par):
                run_dirs = [root / "runs" / a["run"] for a in trusted_failures(window(st))
                            if root is not None and a.get("run")] or None
                cuts = cut_maps(window(st), seen, run_dirs)
                if cuts:
                    doc["splits"][seg.goal] = cuts
                    done.append(seg.goal)
                else:
                    st["split_retry_at"] = st["n"] + WINDOW
        seen |= {m for a in st["attempts"] for m in a.get("maps", [])}
    return done


def parent_segment(doc: dict, goal: str) -> Segment | None:
    """The whole-goal segment a split hid: same start as its first piece, its own goal as the stop."""
    piece = next((s for s in layout(doc) if s.goal == goal), None)
    return Segment(goal, goal, piece.start, goal, goal, None) if piece else None


def should_rejoin(doc: dict, goal: str, grades, pieces) -> bool:
    """Undo a split when every piece is solved+optimized AND the parent has REJOIN_PROBES consecutive
    rejoin-tagged probe solves within REJOIN_TOL of the pieces' accepted-best sum."""
    gmap = {g.key: g for g in grades}
    if not pieces or not all((g := gmap.get(p.key)) is not None and g.solved and g.optimized for p in pieces):
        return False
    bests = []
    for p in pieces:
        b = accepted(stat(doc, p.key))
        if b is None:
            return False
        bests.append(b["frames"])
    total = sum(bests)
    probes = [a for a in stat(doc, goal)["attempts"] if a.get("rejoin")]
    last = probes[-REJOIN_PROBES:]
    return len(last) == REJOIN_PROBES and all(a["solved"] and abs(a["frames"] - total) <= REJOIN_TOL * total
                                              for a in last)


def reset(doc: dict, goals: list[str] | None = None) -> list[str]:
    """Undo splits (all, or the named goals); the sub-segments' stats are dropped, the parent's history is kept."""
    out = []
    for g in list(doc["splits"]):
        if goals is None or g in goals:
            del doc["splits"][g]
            for k in [k for k in doc["stats"] if k.startswith(f"{g}@")]:
                del doc["stats"][k]
            doc["stats"].get(g, {}).pop("split_retry_at", None)
            out.append(g)
    return out
