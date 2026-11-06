"""mash_skill: learn, per situation, how to get through a busy screen fastest (wait, or A at some pace).

A situation is a signature (map, screen kind, joypad-ignored flag, first text line). Each episode (busy until
the screen is controllable again) is graded by FRAMES to resolution; presses are only a tiebreak. The choice is an
epsilon-greedy bandit with an optimistic start, stored in maps.json under "mash_skill"."""
from __future__ import annotations

import random

WAIT = "WAIT"
STRATEGIES = (WAIT, "A/4", "A/8", "A/16", "A/32")  # A every N frames; decisions land every frames_per_step frames
EPSILON = 0.1
PRESS_TIEBREAK = 0.01  # frames-equivalent cost of one press (a tiebreak, not a penalty)
BOUND_FRAMES = 90  # even WAIT spends one A after this long (a stuck cutscene may be waiting for it)


def gap_frames(strategy: str) -> int:
    """Frames between A presses for a strategy (WAIT = the bound)."""
    return BOUND_FRAMES if strategy == WAIT else int(strategy.split("/")[1])


def signature(map_id: int, battling: bool, joy_ignored: bool, first_line: str = "") -> str:
    return f"{map_id}|{'battle' if battling else 'overworld'}|j{int(bool(joy_ignored))}|{first_line.strip()[:16]}"


class MashSkill:
    def __init__(self, data: dict, rng: random.Random | None = None):
        self.table: dict = data.setdefault("mash_skill", {})
        self.rng = rng or random.Random(0)

    def _global(self, strategy: str) -> tuple[int, float, float]:
        n = f = p = 0.0
        for per in self.table.values():
            e = per.get(strategy)
            if e:
                n += e["n"]; f += e["n"] * e["mean_frames"]; p += e["n"] * e["mean_presses"]
        return (int(n), f / n, p / n) if n else (0, 0.0, 0.0)

    def _score(self, sig: str, strategy: str) -> float:
        e = self.table.get(sig, {}).get(strategy)
        if e and e["n"]:
            return e["mean_frames"] + PRESS_TIEBREAK * e["mean_presses"]
        n, frames, presses = self._global(strategy)  # unknown here: start from the global figure,
        return frames + PRESS_TIEBREAK * presses if n else 0.0  # or optimistic (0 frames) if never tried anywhere

    def choose(self, sig: str) -> str:
        if self.rng.random() < EPSILON:
            return self.rng.choice(STRATEGIES)
        return min(STRATEGIES, key=lambda s: (self._score(sig, s), STRATEGIES.index(s)))

    def mean_frames(self, sig: str, strategy: str) -> int:
        return round(self._score(sig, strategy))

    def record(self, sig: str, strategy: str, frames: int, presses: int) -> None:
        e = self.table.setdefault(sig, {}).setdefault(strategy, {"n": 0, "mean_frames": 0.0, "mean_presses": 0.0})
        e["n"] += 1
        e["mean_frames"] += (frames - e["mean_frames"]) / e["n"]
        e["mean_presses"] += (presses - e["mean_presses"]) / e["n"]
        e["mean_frames"], e["mean_presses"] = round(e["mean_frames"], 2), round(e["mean_presses"], 2)
