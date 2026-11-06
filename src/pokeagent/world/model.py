"""World aggregator: merges every agent's event stream into per-agent tracks and one union of learnings.

``WorldModel.poll(sources)`` reads ``src.events(since)`` from each agent concurrently on a small pool (bounded timeouts live
in the source, same rules as the viewer poller); ``ingest`` applies events. All reads copy out under the lock.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable

from pokeagent.world import events as ev

TRAIL = 400
FEED = 600
POLL_S = 0.2
CLOSE_AFTER_S = 4.0


@dataclass
class BattleCard:
    species: str = ""
    enemy_level: int = 0
    own_species: str = ""
    own_level: int = 0
    hp: int = 0
    max_hp: int = 0
    enemy_hp: int = 0
    enemy_max_hp: int = 0
    turn: int = 0
    move: str = ""
    effect: str = ""
    plan: str = ""
    result: str = ""
    ended_at: float | None = None


@dataclass
class Track:
    id: str
    map: int = -1
    x: int = 0
    y: int = 0
    facing: str = "DOWN"
    step: int = 0
    prev: tuple[int, int, int] | None = None     # where the last move came from (map, x, y)
    moved_at: float = 0.0                        # viewer clock when the last move arrived
    path: deque = field(default_factory=lambda: deque(maxlen=TRAIL))   # (map, x, y)
    goal: str = ""
    hold: bool = False
    stalled: bool = False
    battle: BattleCard | None = None
    last_seq: int = 0

    @property
    def placed(self) -> bool:
        return self.map >= 0


@dataclass(frozen=True)
class Learned:
    kind: str
    map: int
    x: int
    y: int
    dir: str
    agent: str          # who learned it first
    t: float
    dest: tuple | None = None
    also: tuple = ()    # others who learned it later


class WorldModel:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._tracks: dict[str, Track] = {}
        self._learned: dict[tuple, Learned] = {}
        self._visits: dict[tuple[int, int, int], int] = {}
        self._feed: deque = deque(maxlen=FEED)        # (agent, event dict, viewer time)
        self._since: dict[str, int] = {}
        self._polled: dict[str, float] = {}
        self._rev = 0                                 # bumps whenever the union of learnings changes
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="world-poll")

    # -- ingest -----------------------------------------------------------------------
    def _read_one(self, src) -> None:
        aid = src.agent_id
        now = self._clock()
        if now - self._polled.get(aid, -1e9) < POLL_S or not hasattr(src, "events"):
            return
        self._polled[aid] = now
        try:
            got = src.events(self._since.get(aid, 0))
        except Exception:
            return
        if got:
            self.ingest(aid, got)

    def poll(self, sources: Iterable) -> None:
        list(self._pool.map(self._read_one, list(sources)))

    def ingest(self, agent_id: str, items: list[dict]) -> None:
        now = self._clock()
        with self._lock:
            tr = self._tracks.setdefault(agent_id, Track(agent_id))
            for d in items:
                e = ev.from_dict(d)
                if e is None or e.seq <= tr.last_seq:
                    continue
                tr.last_seq = self._since[agent_id] = e.seq
                self._apply(tr, e, now)
                self._feed.append((agent_id, d, now))

    def _apply(self, tr: Track, e: ev.Event, now: float) -> None:
        if isinstance(e, ev.Move):
            if tr.placed:
                tr.prev = (tr.map, tr.x, tr.y)
            tr.map, tr.x, tr.y, tr.facing, tr.step, tr.moved_at, tr.stalled = e.map, e.x, e.y, e.facing, e.step, now, False
            tr.path.append((e.map, e.x, e.y))
            key = (e.map, e.x, e.y)
            self._visits[key] = self._visits.get(key, 0) + 1
        elif isinstance(e, ev.MapChange):
            tr.prev = None                                       # no sliding across a warp
        elif isinstance(e, ev.BattleStart):
            tr.battle = BattleCard(**{k: getattr(e, k) for k in BattleCard.__dataclass_fields__ if hasattr(e, k)})
        elif isinstance(e, ev.BattleTurn) and tr.battle:
            c = tr.battle
            c.turn, c.hp, c.max_hp, c.enemy_hp, c.enemy_max_hp = e.turn, e.hp, e.max_hp, e.enemy_hp, e.enemy_max_hp
            c.move, c.effect, c.plan = e.move or c.move, e.effect or c.effect, e.plan or c.plan
        elif isinstance(e, ev.BattleEnd) and tr.battle:
            tr.battle.result, tr.battle.ended_at = e.result or "ended", now
        elif isinstance(e, ev.Goal) and e.status == "current":
            tr.goal = e.name
        elif isinstance(e, ev.Stall):
            tr.stalled = True
        elif isinstance(e, ev.HumanHold):
            tr.hold = e.on
        elif isinstance(e, ev.Learn):
            self._learn(tr.id, e)

    def _learn(self, agent: str, e: ev.Learn) -> None:
        key = (e.kind, e.map, e.x, e.y, e.dir)
        cur = self._learned.get(key)
        if cur is None:
            self._learned[key] = Learned(e.kind, e.map, e.x, e.y, e.dir, agent, e.t, tuple(e.dest) if e.dest else None)
            self._rev += 1
        elif agent != cur.agent and agent not in cur.also:
            self._learned[key] = replace(cur, also=cur.also + (agent,))

    # -- reads ------------------------------------------------------------------------
    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._tracks)

    def tracks(self) -> list[Track]:
        with self._lock:
            return [replace(t, path=deque(t.path, maxlen=TRAIL), battle=replace(t.battle) if t.battle else None)
                    for _, t in sorted(self._tracks.items())]

    def track(self, agent_id: str) -> Track | None:
        return next((t for t in self.tracks() if t.id == agent_id), None)

    def forget(self, agent_id: str) -> None:
        with self._lock:
            self._tracks.pop(agent_id, None)
            self._since.pop(agent_id, None)

    @property
    def rev(self) -> int:
        return self._rev

    def learned(self) -> list[Learned]:
        with self._lock:
            return list(self._learned.values())

    def who_learned(self, map_id: int, x: int, y: int) -> list[Learned]:
        with self._lock:
            return [v for v in self._learned.values() if (v.map, v.x, v.y) == (map_id, x, y)]

    def union_model(self) -> dict:
        """The union of every agent's learnings in the overlay's maps.json shape."""
        with self._lock:
            maps: dict[str, dict] = {}
            for (m, x, y), n in self._visits.items():
                maps.setdefault(str(m), {}).setdefault("visited", {})[f"{x},{y}"] = n
            for v in self._learned.values():
                d = maps.setdefault(str(v.map), {})
                k = f"{v.x},{v.y},{v.dir}"
                if v.kind == "wall":
                    d.setdefault("blocked", []).append(k)
                elif v.kind == "warp":
                    d.setdefault("warps", {})[k] = list(v.dest or (0, 0, 0))
                elif v.kind == "jump":
                    d.setdefault("jumps", {})[k] = list(v.dest or (v.x, v.y, 0))
                elif v.kind == "encounter":
                    e = d.setdefault("encounters", {})
                    e[f"{v.x},{v.y}"] = e.get(f"{v.x},{v.y}", 0) + 1
            return {"maps": maps}

    def feed(self, kinds: set[str] | None = None, limit: int = 60) -> list[tuple[str, dict]]:
        """Newest-last recent events across agents; ``kinds`` filters by event type."""
        with self._lock:
            rows = [(a, d) for a, d, _ in self._feed if not kinds or d.get("type") in kinds]
        return rows[-limit:]

    def stadium(self, now: float | None = None, close_after: float = CLOSE_AFTER_S) -> list[tuple[str, BattleCard]]:
        """Agents whose battle is open (or ended less than ``close_after`` s ago), oldest battle first."""
        now = self._clock() if now is None else now
        return [(t.id, t.battle) for t in self.tracks()
                if t.battle and (t.battle.ended_at is None or now - t.battle.ended_at < close_after)]
