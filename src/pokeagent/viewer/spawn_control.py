"""Viewer-side spawn state: the one-in-flight/debounce guard, the last refusal, and a cached "at the cap" status
so the UI thread reads the registry and system memory at most every 2 s, and never on the UI thread."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from pokeagent import resources
from pokeagent.supervisor import swarm_running_message
from pokeagent.viewer.view_cap import SpawnGuard

REFRESH_S = 2.0


class SpawnControl:
    def __init__(self, supervisor, root: Path | None, clock: Callable[[], float] = time.monotonic,
                 limits: dict | None = None, probe: Callable | None = None) -> None:
        self.supervisor, self.root = supervisor, root
        self._clock, self._limits = clock, limits or {}
        self._probe = probe or resources.headroom
        self._guard = SpawnGuard(clock)
        self._last = float("-inf")
        self._busy = False
        self.capped = False
        self.refused = ""   # last SpawnRefused/launch error
        self.status = ""    # cached cap/swarm explanation

    @property
    def message(self) -> str:
        return self.refused or self.status

    def refresh(self, force: bool = False) -> None:
        """Recompute the cap status at most every REFRESH_S. Cheap to call every UI frame; the work runs on a
        daemon thread unless ``force`` (tests)."""
        if self.root is None or self._busy or (not force and self._clock() - self._last < REFRESH_S):
            return
        self._last = self._clock()
        if force:
            self._compute()
        else:
            self._busy = True
            threading.Thread(target=self._compute, daemon=True, name="viewer-capcheck").start()

    def _compute(self) -> None:
        try:
            if resources.lock_held(self.root):
                self.capped, self.status = True, swarm_running_message(self.root)
                return
            room, mx, live = self._probe(self.root, **self._limits)
            self.capped = room < 1
            self.status = f"agent limit reached ({live} of max {mx})" if self.capped else ""
        except Exception:  # a failed probe must not break the UI; keep the previous status
            pass
        finally:
            self._busy = False

    def spawn(self, kind: str, args: str) -> None:
        if self.supervisor is None or not self._guard.begin():
            return  # no supervisor, a spawn in flight, or a repeat callback inside the 2 s debounce
        try:
            self.supervisor.spawn(*([kind] + (args.split() if args else [])))
            self.refused = ""
        except Exception as e:  # SpawnRefused or a launch failure: show it, never crash the UI
            self.refused = str(e)
        finally:
            self._guard.end()
            self._last = float("-inf")  # re-check the cap on the next frame
