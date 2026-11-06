"""``pokeagent view``: discover agents, poll the model in a thread, draw the Dear PyGui window.

``run(root, fps=30)`` is the entry point; ``--fake N`` swaps discovery for animated synthetic
agents (demos/tests). ``--web`` additionally serves the read-only page on 127.0.0.1.
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

import numpy as np

from pokeagent.agent_registry import list_agents
from pokeagent.snapshot import AgentSnapshot, Goal, Screen, Sees, Segment, Thinking
from pokeagent.viewer.model import ViewerModel
from pokeagent.world.events import BattleEnd, BattleStart, EventBus, Move
from pokeagent.world.model import WorldModel
from pokeagent.viewer.sources import AgentSource, HttpShmSource, discover

log = logging.getLogger(__name__)
SNAPSHOT_HZ = 10.0  # spec: snapshots 10 Hz, frames 30 Hz


class _Throttle:
    """AgentSource wrapper: snapshot() at most every ``interval`` s; frame/send pass through."""

    def __init__(self, src: AgentSource, interval: float = 1.0 / SNAPSHOT_HZ) -> None:
        self._src, self._interval = src, interval
        self._snap: AgentSnapshot | None = None
        self._at = 0.0

    @property
    def agent_id(self) -> str:
        return self._src.agent_id

    def snapshot(self) -> AgentSnapshot | None:
        now = time.monotonic()
        if now - self._at >= self._interval:
            self._at, self._snap = now, self._src.snapshot()
        return self._snap

    def frame(self):
        return self._src.frame()

    def events(self, since: int = 0) -> dict:
        fn = getattr(self._src, "events", None)
        return fn(since) if fn else {"events": []}

    def send(self, cmd: str, **args) -> dict:
        return self._src.send(cmd, **args)


class _AnimatedFake:
    """Synthetic agent for --fake: snapshot/frame change every poll; send() records commands."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._t = 0
        self.sent: list[tuple[str, dict]] = []
        self._bus = EventBus()
        self._pos = [[0, 5, 6], [1, 12, 10], [2, 10, 9], [3, 14, 10]][hash(agent_id) % 4]

    def events(self, since: int = 0) -> dict:
        """Wander on a loop (one cell per poll) and fight every 40th step, so --fake shows the world view moving."""
        t, (m, x, y) = self._t, self._pos
        face = ("RIGHT", "DOWN", "LEFT", "UP")[t // 6 % 4]
        dx, dy = {"RIGHT": (1, 0), "DOWN": (0, 1), "LEFT": (-1, 0), "UP": (0, -1)}[face]
        self._pos[1], self._pos[2] = x + dx, y + dy
        self._bus.emit(Move(map=m, x=x + dx, y=y + dy, facing=face, step=t))
        if t % 40 == 20:
            self._bus.emit(BattleStart(species="PIDGEY", enemy_level=3, own_species="CHARMANDER", own_level=5,
                                       hp=19, max_hp=19, enemy_hp=12, enemy_max_hp=12))
        if t % 40 == 30:
            self._bus.emit(BattleEnd(result="won", turns=3))
        return self._bus.payload(since)

    def snapshot(self) -> AgentSnapshot:
        self._t += 1
        t = self._t
        glyphs = "@NTo#o~!W"
        rows = ["".join(glyphs[(i * 7 + t + j) % len(glyphs)] for j in range(10)) for i in range(9)]
        return AgentSnapshot(
            agent_id=self.agent_id, kind="explorer" if t % 2 else "rl", state="running",
            step=t, segment=Segment(id="S3", name="first_pokemon", steps=3),
            goals=[Goal(id="g1", name="first_pokemon", steps=3)],
            thinking=Thinking(want="reach route 4", plan="walk north", driver="explorer",
                              rule="rule-17", button="UP", result="moved", confidence=0.8,
                              brain="OVERWORLD -> A(0.07)" if t % 2 else ""),
            drivers_available=["explorer", "rl", "human"],
            recent=[], sees=Sees(rows=rows, mode="overworld"),
            screen=Screen(box_text=f"fake {self.agent_id} t={t}", in_battle=False),
            human_hold=False, updated_at=time.time())

    def frame(self):
        t = self._t
        w, h = 160, 144
        y, x = np.mgrid[0:h, 0:w]
        px = np.stack([(x * 3 + t) % 256, (y * 5 + t * 2) % 256, ((x + y) * 2 + t) % 256], axis=-1)
        return px.astype(np.uint8).tobytes(), w, h

    def send(self, cmd: str, **args) -> dict:
        self.sent.append((cmd, args))
        return {"ok": True}


def animated_fakes(n: int) -> list[_AnimatedFake]:
    return [_AnimatedFake(f"fake-{i + 1}") for i in range(n)]


def _sources_for(root: Path, fake: int) -> tuple[dict, dict]:
    """agent_id -> live source and agent_id -> registry entry (pid/kind for spawn/stop)."""
    if fake:
        srcs = {s.agent_id: s for s in animated_fakes(fake)}
        return srcs, {}
    entries = {str(e["id"]): e for e in list_agents(root)}
    return {aid: HttpShmSource(e) for aid, e in entries.items()}, entries


def merge_sources(current: dict, fresh: dict) -> tuple[list[str], list[str]]:
    """Reconcile ``current`` (agent_id -> _Throttle) with ``fresh`` (agent_id -> source) in place:
    keep existing throttles for agents still present, add new ones, drop vanished ones."""
    gone = [aid for aid in current if aid not in fresh]
    for aid in gone:
        del current[aid]
    added = [aid for aid in fresh if aid not in current]
    for aid in added:
        current[aid] = _Throttle(fresh[aid])
    return added, gone


def refresh_sources(holder: dict, model, fresh: dict, new_entries: dict) -> list[str]:
    """Apply a registry re-scan. An agent whose registry entry is gone has exited: forget its card at once
    (``model.prune`` would keep it as 'lost' for 60 s). Returns the dropped ids."""
    _added, gone = merge_sources(holder["sources"], fresh)
    for aid in gone:
        model.forget(aid)
    holder["entries"].clear()
    holder["entries"].update(new_entries)
    return gone


def run(root, fps: int = 30, fake: int = 0, web: bool = False, web_port: int = 8899, world_mode: bool = False) -> int:
    root = Path(root)
    sources, entries = _sources_for(root, fake)
    model = ViewerModel()
    world = WorldModel()
    holder = {"sources": {aid: _Throttle(s) for aid, s in sources.items()}, "entries": entries}
    stop = threading.Event()

    def poller() -> None:
        ticks, warned = 0, False
        while not stop.is_set():
            ticks += 1
            # re-discover real agents every ~2 s (60 ticks at 30 fps) so spawns appear, exits vanish
            if not fake and ticks % 60 == 0:
                try:
                    fresh, new_entries = _sources_for(root, fake)
                    refresh_sources(holder, model, fresh, new_entries)
                    model.prune()
                except Exception:
                    if not warned:  # once: a persistent failure must not flood the log every 2 s
                        log.exception("agent re-discovery failed (further failures suppressed)")
                        warned = True
            model.poll(list(holder["sources"].values()))
            world.poll(list(holder["sources"].values()))
            time.sleep(1.0 / fps)

    threading.Thread(target=poller, daemon=True).start()

    if web:
        from pokeagent.viewer import web as webview
        webview.serve_threaded(model, web_port)

    from pokeagent.viewer.ui.window import ViewerWindow
    from pokeagent.supervisor import Supervisor
    win = ViewerWindow(model, holder["sources"], fps=fps, supervisor=Supervisor(root),
                       root=root, world=world)
    win.entries = entries
    if world_mode:
        win.focus.set_mode("world")
    try:
        win.run()
    finally:
        stop.set()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pokeagent view", description="Dear PyGui viewer for PokeAgent agents.")
    p.add_argument("--root", default=".", help="agent registry root (default: cwd)")
    p.add_argument("--fake", type=int, default=0, metavar="N", help="show N animated fake agents")
    p.add_argument("--web", action="store_true", help="also serve the read-only web view")
    p.add_argument("--port", type=int, default=8899, help="web view port (default 8899)")
    p.add_argument("--fps", type=int, default=30, help="poll/UI rate (default 30)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return run(args.root, fps=args.fps, fake=args.fake, web=args.web, web_port=args.port)


if __name__ == "__main__":
    sys.exit(main())
