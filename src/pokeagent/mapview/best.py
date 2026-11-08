"""Which ghost is "best": the one whose LAST point reached furthest, by (area rank, x).

Chosen over trusting the ``outcome`` label - other writers may not produce a "best" label, so a
labelled ghost is not special here. Area rank is the area's position in the index order (the same
order ``Ghost.area_idx`` indexes into); a ghost whose last area is not in ``area_order`` ranks
below all known ones.
"""
from __future__ import annotations


def best_index(ghosts, area_order) -> int | None:
    """Index of the furthest ghost, or None for none. Ties: fewer points, then the earlier run."""
    span = len(area_order)
    pick, top = None, None
    for k, g in enumerate(ghosts):
        if not len(g.xs):
            continue
        rank = int(g.area_idx[-1])
        key = (rank if 0 <= rank < span else -1, float(g.xs[-1]))
        tie = (len(g.xs), g.run)
        if top is None or key > top[0] or (key == top[0] and tie < top[1]):
            pick, top = k, (key, tie)
    return pick
