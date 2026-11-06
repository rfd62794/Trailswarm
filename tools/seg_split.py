"""Auto-split: a segment that keeps failing is cut at natural sub-milestones (first entry into each new map id).

Trigger: >= MIN_ATTEMPTS attempts and a solve rate under SPLIT_RATE over the last window. Cut points come only from
TRUSTED partial attempts (failed, tagged curriculum runs whose frames were not estimated): the map ids, in order of first
entry, along the failed attempt that got furthest. A cut map must (1) not be the segment's own start map, (2) not appear
in any earlier segment's attempts (it is part of the way TO this segment, not progress in it) and (3) be reached by at
least MIN_REACH of the trusted failed attempts. The pieces get their own checkpoints and stats and chain back together
(seg_store.layout); the original segment's history is kept but unused. reset() undoes a split.
"""
from __future__ import annotations

from seg_store import WINDOW, layout, rate, stat, window

MIN_ATTEMPTS = 20
SPLIT_RATE = 0.30
MAX_CUTS = 4
MIN_REACH = 2


def trusted_failures(attempts: list[dict]) -> list[dict]:
    return [a for a in attempts if not a["solved"] and a.get("maps") and a.get("tagged") and not a.get("est")]


def cut_maps(attempts: list[dict], earlier: set[int] = frozenset()) -> list[int]:
    failed = trusted_failures(attempts)
    if len(failed) < MIN_REACH:
        return []
    starts = {a["maps"][0] for a in failed}
    reach: dict[int, int] = {}
    for a in failed:
        for m in a["maps"][1:]:
            reach[m] = reach.get(m, 0) + 1
    best = max(failed, key=lambda a: len(a["maps"]))
    return [m for m in best["maps"][1:]
            if m not in starts and m not in earlier and reach.get(m, 0) >= MIN_REACH][:MAX_CUTS]


def should_split(st: dict) -> bool:
    r = rate(st)
    if st["n"] < MIN_ATTEMPTS or len(window(st)) < WINDOW or r is None or r >= SPLIT_RATE:
        return False
    return st["n"] >= st.get("split_retry_at", 0)


def maybe_split(doc: dict) -> list[str]:
    """Split every top-level segment that qualifies; returns the goals split. Unsplittable ones retry after WINDOW more."""
    done = []
    seen: set[int] = set()   # maps in the attempts of the segments before this one
    for seg in layout(doc):
        st = stat(doc, seg.key)
        if seg.key == seg.goal and should_split(st):
            cuts = cut_maps(window(st), seen)
            if cuts:
                doc["splits"][seg.goal] = cuts
                done.append(seg.goal)
            else:
                st["split_retry_at"] = st["n"] + WINDOW
        seen |= {m for a in st["attempts"] for m in a.get("maps", [])}
    return done


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
