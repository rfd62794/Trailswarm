"""Auto-split: a segment that keeps failing is cut at natural sub-milestones (first entry into each new map id).

Trigger: >= MIN_ATTEMPTS attempts and a solve rate under SPLIT_RATE over the last window. The cut points come from the
partial attempts' paths: the map ids, in order of first entry, along the failed attempt that got furthest, keeping only
maps that at least two failed attempts reached (one lucky wander is not a milestone). The pieces get their own
checkpoints and stats and chain back together (seg_store.layout); the original segment's history is kept but unused.
"""
from __future__ import annotations

from seg_store import WINDOW, layout, rate, stat, window

MIN_ATTEMPTS = 20
SPLIT_RATE = 0.30
MAX_CUTS = 4


def cut_maps(attempts: list[dict]) -> list[int]:
    failed = [a for a in attempts if not a["solved"] and a.get("maps")]
    if not failed:
        return []
    best = max(failed, key=lambda a: len(a["maps"]))
    reach: dict[int, int] = {}
    for a in failed:
        for m in a["maps"][1:]:
            reach[m] = reach.get(m, 0) + 1
    need = 2 if len(failed) >= 2 else 1
    return [m for m in best["maps"][1:] if reach.get(m, 0) >= need][:MAX_CUTS]


def should_split(st: dict) -> bool:
    r = rate(st)
    if st["n"] < MIN_ATTEMPTS or len(window(st)) < WINDOW or r is None or r >= SPLIT_RATE:
        return False
    return st["n"] >= st.get("split_retry_at", 0)


def maybe_split(doc: dict) -> list[str]:
    """Split every top-level segment that qualifies; returns the goals split. Unsplittable ones retry after WINDOW more."""
    done = []
    for seg in layout(doc):
        if seg.key != seg.goal:
            continue  # sub-segments are not split again
        st = stat(doc, seg.key)
        if not should_split(st):
            continue
        cuts = cut_maps(window(st))
        if not cuts:
            st["split_retry_at"] = st["n"] + WINDOW
            continue
        doc["splits"][seg.goal] = cuts
        done.append(seg.goal)
    return done
