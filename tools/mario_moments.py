"""Scored moments: turn per-frame score jumps into a ranked, replayable highlights list.

Pure logic, no emulator. An event is a dict with frame, move, area, x, y, kind and points. Kinds are:
    kill   score rose with an enemy close to the player (inferred, the game does not report kills)
    coin   the coin counter rose on the same frame
    block  score rose with nothing else to explain it
    bonus  the end-of-level timer tally, never a highlight
"""
import numpy as np

STREAK_GAP = 90            # frames between events that still count as one moment
NEAR_TILES = 3
KEEP = 100
TAIL_MOVES = 4             # moves kept after a moment so a clip can show how it ended
MARIO, ENEMY = 1, 4


def classify(points, coins_rose, timer_dropped, grid):
    if timer_dropped:
        return "bonus"
    if coins_rose:
        return "coin"
    return "kill" if enemy_near(grid) else "block"


def enemy_near(grid):
    g = np.asarray(grid)
    players, enemies = np.argwhere(g == MARIO), np.argwhere(g == ENEMY)
    if len(players) == 0 or len(enemies) == 0:
        return False
    dist = np.abs(players[:, None, :] - enemies[None, :, :]).max(axis=2)
    return bool(dist.min() <= NEAR_TILES)


def group(events):
    """Split time-ordered events into streaks, dropping timer bonuses."""
    streaks, current = [], []
    for e in events:
        if e["kind"] == "bonus":
            continue
        if current and (e["frame"] - current[-1]["frame"] > STREAK_GAP or e["area"] != current[-1]["area"]):
            streaks.append(current)
            current = []
        current.append(e)
    if current:
        streaks.append(current)
    return streaks


def rank_of(points, kills, coins, blocks):
    if kills == 0:
        return points * 0.25
    return points + 300 * kills + 200 * (kills - 1)


def describe(kills, coins, blocks, points, frames):
    parts = []
    if kills:
        parts.append(f"{kills} likely kill{'s' if kills != 1 else ''}")
    if coins:
        parts.append(f"{coins} coin{'s' if coins != 1 else ''}")
    if blocks:
        parts.append(f"{blocks} block{'s' if blocks != 1 else ''}")
    return f"{' + '.join(parts)}, +{points} in {frames / 60:.1f}s"


def to_moment(streak, doc):
    kinds = [e["kind"] for e in streak]
    kills, coins, blocks = kinds.count("kill"), kinds.count("coin"), kinds.count("block")
    points = sum(e["points"] for e in streak)
    first, last = streak[0], streak[-1]
    return {"key": f"{first['area']}:{first['x'] // 16}:{kills}:{coins}:{blocks}:{points}",
            "area": first["area"], "x": first["x"], "y": first["y"], "frame": first["frame"], "end_frame": last["frame"],
            "points": points, "kills": kills, "coins": coins, "blocks": blocks,
            "rank": rank_of(points, kills, coins, blocks),
            "why": describe(kills, coins, blocks, points, last["frame"] - first["frame"]),
            "agent": f"worker-{doc['worker']}", "seq": doc["seq"][:last["move"] + TAIL_MOVES]}


class MomentBook:
    def __init__(self, keep=KEEP):
        self.keep = keep
        self.moments = {}
        self.dirty = False

    def add(self, events, doc):
        for streak in group(events):
            m = to_moment(streak, doc)
            if m["key"] not in self.moments:
                self.moments[m["key"]] = m
                self.dirty = True
        if len(self.moments) > self.keep:
            top = sorted(self.moments.values(), key=lambda m: -m["rank"])[: self.keep]
            self.moments = {m["key"]: m for m in top}

    def ranked(self):
        return sorted(self.moments.values(), key=lambda m: -m["rank"])
