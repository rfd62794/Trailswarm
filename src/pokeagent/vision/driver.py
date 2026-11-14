"""Where the recorder's presses come from: a script file or a seeded random walk. No game logic."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokeagent.emulator import Button

DIRECTIONS = ("up", "down", "left", "right")
ALL_BUTTONS = ("up", "down", "left", "right", "a", "b")
HOLD, SETTLE = 8, 16
A_EVERY = 10                # the Red default adds an `a` press about every tenth press


def _button(name: str) -> Button:
    from pokeagent.emulator import Button    # local: keeps this module PyBoy-free at import
    return Button(name)


class ScriptDriver:
    """Replays {"game", "start_state": "<path or null>", "presses": [[button, hold, settle], ...]}."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.game = doc.get("game")
        self.start_state = doc.get("start_state")
        self._presses = doc["presses"]

    def iter_presses(self):
        """Yield (Button, hold, settle) per script row."""
        for name, hold, settle in self._presses:
            yield _button(name), hold, settle


class RandomWalkDriver:
    """A seeded random walk: random.Random(seed) chooses a button per press, holds 8, settles 16.

    buttons=None defaults to directions only; every ``a_every``-th press is `a` instead of a random
    pick (the Red default); a_every=0 disables it. Deterministic for a seed, different for another."""

    def __init__(self, seed: int, n_presses: int, buttons=None, a_every: int = A_EVERY) -> None:
        self._rng = random.Random(seed)
        self._n, self._a_every = n_presses, a_every
        self._buttons = tuple(buttons) if buttons else DIRECTIONS

    def iter_presses(self):
        """Yield (Button, hold, settle), deterministic for the seed."""
        for i in range(self._n):
            name = "a" if self._a_every and (i + 1) % self._a_every == 0 else self._rng.choice(self._buttons)
            yield _button(name), HOLD, SETTLE
