"""The Mario side of the live-position contract: build and throttle live/<agent>.json.

The display calls ``build_record`` for the emulator's current state and ``maybe_write``
throttles the file writes; the Map view reads the result on its own clock. Position maths
is shared with the ghost writer through ``mario_maps.track_point``, never duplicated.
"""
import time
from pathlib import Path

from mario_maps import track_point

from pokeagent.mapview.live import write_live

# filled in by the real-window check; see Required from User
PLAYER_TILE_IDS: frozenset[int] = frozenset()


def locate_player(sprites, tile_ids) -> tuple[int, int] | None:
    """Top-left of the bounding box of the sprites whose tile id is in ``tile_ids``;
    ``sprites`` is a list of (x, y, tile_id). None when none match."""
    pts = [(x, y) for x, y, t in sprites if t in tile_ids]
    return (min(x for x, _ in pts), min(y for _, y in pts)) if pts else None


def locate_box(sprites, tile_ids) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the bounding box of the matching 8x8 sprites, or None when none match."""
    pts = [(x, y) for x, y, t in sprites if t in tile_ids]
    if not pts:
        return None
    x0, y0 = min(x for x, _ in pts), min(y for _, y in pts)
    return x0, y0, max(x for x, _ in pts) - x0 + 8, max(y for _, y in pts) - y0 + 8


def build_record(display) -> dict | None:
    """The schema-1 live record for the display's current emulator state, or None."""
    try:
        area, x, y = track_point(display.w, display.py.memory)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        return None
    sx = sy = sw = sh = None
    if PLAYER_TILE_IDS:
        try:
            sprites = [(s.x, s.y, s.tile_identifier)
                       for s in (display.py.botsupport().sprite(i) for i in range(40))]
            if (box := locate_box(sprites, PLAYER_TILE_IDS)) is not None:
                sx, sy, sw, sh = box
        except Exception:
            pass                                            # sprite read is best-effort
    doc = display.best or {}
    try:
        run = f"{int(doc['at'] * 1000)}-{doc['worker']}"    # same id the ghost writer gives
    except (KeyError, TypeError):
        run = ""
    return {"schema": 1, "agent": getattr(display, "agent", "mario-land"), "run": run,
            "area": str(area), "x": float(x), "y": float(y),
            "screen_x": sx, "screen_y": sy, "screen_w": sw, "screen_h": sh, "updated_at": time.time()}


class LiveWriter:
    """Writes the live record through ``write_live`` at most ``hz`` times a second."""

    def __init__(self, source: Path, agent: str, hz: float = 10.0) -> None:
        self.source, self.agent, self.hz = Path(source), agent, float(hz)
        self._last = float("-inf")

    def due(self, now: float) -> bool:
        """True when a write would pass the throttle; check it before building a record."""
        return now - self._last >= 1.0 / self.hz

    def maybe_write(self, state: dict, now: float) -> None:
        """``state`` is a record from ``build_record``; ``now`` is monotonic. No sleeping."""
        if not state or not self.due(now):
            return
        self._last = now
        write_live(self.source, {**state, "agent": self.agent})
