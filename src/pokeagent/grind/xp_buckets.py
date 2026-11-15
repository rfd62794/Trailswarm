"""Measured xp/min by trainee level bucket: a solo L6's rate is not a switch-trained L12's.

The ledger format is additive: an episode value gains an optional 4th element, the trainee's
``BUCKET``-sized level bucket (L5-9 -> 5, L10-14 -> 10). A 3-element value - every ledger and
swarm table written before this - belongs to the default bucket (``None``). ``points._recompute``
keeps the all-bucket mean so the swarm merge and every other reader are untouched; ``choose``
prefers the trainee's own bucket when it holds at least MIN_MEASURED episodes.
"""
BUCKET = 5   # levels per bucket


def bucket_of(level: int | None) -> int | None:
    """The bucket a trainee level belongs to (5 -> 5, 9 -> 5, 10 -> 10); None = the default bucket."""
    return None if level is None else level // BUCKET * BUCKET


def _tag(v) -> int | None:
    return v[3] if len(v) > 3 else None  # a 3-element value is the default bucket


def measured_for(p, level) -> tuple[float, int] | None:
    """(mean xp/min, n) over the episodes tagged with the trainee's bucket, else the default
    bucket's, else None. The caller applies the MIN_MEASURED rule to ``n``."""
    b = bucket_of(level)
    mine = [v[0] for v in p.episodes.values() if _tag(v) == b]
    if mine:
        return sum(mine) / len(mine), len(mine)
    base = [v[0] for v in p.episodes.values() if _tag(v) is None]
    return (sum(base) / len(base), len(base)) if base else None
