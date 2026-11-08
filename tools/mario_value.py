"""Style value for the Mario Land search: what breaks a tie between runs that got equally far.

Pure logic, no emulator. Distance is always compared first (the cell key); value only decides within a cell
and between best files at equal distance. Kinds come from mario_moments.classify: kill, coin, block, bonus.
"""
KILL_WEIGHT = 200            # added on top of the points the game awards, per inferred kill
COIN_WEIGHT = 50             # per coin pickup
BLOCK_WEIGHT = 150           # per block hit, so that hitting blocks is rewarded
WEIGHTS = {"kill": KILL_WEIGHT, "coin": COIN_WEIGHT, "block": BLOCK_WEIGHT}


def event_value(kind, points):
    """Value of one score event. The end-of-level timer tally is never style."""
    if kind not in WEIGHTS:
        return 0
    return points + WEIGHTS[kind]


def add_event(value, kind, points):
    return value + event_value(kind, points)


def should_replace(old_value, old_lives, new_value, new_lives, old_progress=0, new_progress=0):
    """A same-cell arrival replaces the stored one only with a strictly higher value, no fewer lives, and no
    less progress within the bucket."""
    return new_value > old_value and new_lives >= old_lives and new_progress >= old_progress


def carried_fails(old_fails, old_progress, new_progress):
    """A replacement keeps the cell's death count unless it also got further, so a cell that only grows in value
    cannot dodge retirement."""
    return 0 if new_progress > old_progress else old_fails


def as_key(doc):
    return ((doc["key"][0][0], doc["key"][0][1]), doc["key"][1])


def best_order(doc):
    """Sort key for best documents: distance first, value second, a missing value counts as 0."""
    return as_key(doc), doc.get("value", 0)
