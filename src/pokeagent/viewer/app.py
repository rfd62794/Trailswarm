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
from pokeagent.game.pokemon_red import RED
from pokeagent.snapshot import AgentSnapshot, Goal, Screen, Sees, Segment, Thinking
from pokeagent.viewer import health as health_mod
from pokeagent.viewer import modes, swarm_rows
from pokeagent.viewer.model import ViewerModel
from pokeagent.world.events import BattleEnd, BattleStart, EventBus, Move
from pokeagent.world.model import WorldModel
from pokeagent.viewer.sources import HttpShmSource, close_source, discover

log = logging.getLogger(__name__)


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
        w, h = RED.screen
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


def merge_sources(current: dict, fresh: dict, missed: dict | None = None) -> tuple[list[str], list[str]]:
    """Reconcile ``current`` (agent_id -> source) with ``fresh`` in place: keep existing sources
    for agents still present, add new ones, drop vanished ones (poll cadences live in the model).
    ``missed`` (agent_id -> consecutive misses): when given, an agent is dropped only after two scans in a row
    miss it, so one unreadable registry file (read during its atomic replace) never drops a live agent."""
    absent = [aid for aid in current if aid not in fresh]
    if missed is None:
        gone = absent
    else:
        for aid in [a for a in missed if a not in absent]:
            missed.pop(aid)                     # seen again (or already dropped): the streak resets
        for aid in absent:
            missed[aid] = missed.get(aid, 0) + 1
        gone = [aid for aid in absent if missed[aid] >= 2]
        for aid in gone:
            missed.pop(aid)
    for aid in gone:
        close_source(current.pop(aid))          # the exited agent's frame-slot handle goes with it
    added = [aid for aid in fresh if aid not in current]
    for aid in added:
        current[aid] = fresh[aid]
    for aid, src in fresh.items():              # a re-scan builds a source for every agent: the ones not adopted are dropped
        if current.get(aid) is not src:
            close_source(src)
    return added, gone


def refresh_sources(holder: dict, model, fresh: dict, new_entries: dict, world=None) -> list[str]:
    """Apply a registry re-scan. An agent whose registry entry is gone has exited: forget its card at once
    (``model.prune`` would keep it as 'lost' for 60 s), and its World-view track too (``world``: a WorldModel;
    any track without a live source is dropped, so dots/trails of dead agents never linger). Returns the dropped ids."""
    _added, gone = merge_sources(holder["sources"], fresh, holder.setdefault("missed", {}))
    for aid in gone:
        model.forget(aid)
    if world is not None:
        world.sweep(holder["sources"])            # tracks, cursors, poll stamps and feed rows of every agent not live
    holder["entries"].clear()
    holder["entries"].update(new_entries)
    return gone


def check_launch(source, game, preset, genre) -> None:
    """Exit 2 with a clear message on an unknown view name or a --source that is not a directory
    (the one check every entry point, `pokeagent view` and `map_view`, goes through via ``run``)."""
    from pokeagent.mapview.presets import name_error
    bad = name_error(game, preset, genre)
    if bad is None and source is not None and not Path(source).is_dir():
        bad = f"--source {str(source)!r} is not an existing directory"
    if bad:
        print("pokeagent view: " + bad, file=sys.stderr)
        raise SystemExit(2)


def run(root, fps: int = 30, fake: int = 0, web: bool = False, web_port: int = 8899, world_mode: bool = False,
        mode: str = modes.DEFAULT_MODE, source=None, game=None, preset=None, genre=None,
        refresh: float | None = None) -> int:
    """One entry point: the same window for `view` and `world`; ``mode`` ('tiles' | 'world') only picks the start view.
    ``source`` is a stitched-map dir (maps/ ghosts/ live/); the preset's world_renderer picks World's renderer."""
    check_launch(source, game, preset, genre)
    root = Path(root)
    sources, entries = _sources_for(root, fake)
    model = ViewerModel()
    world = WorldModel()
    stitched = _stitched_source(source, model, game, preset, genre, fps=fps, refresh=refresh)
    holder = {"sources": dict(sources), "entries": entries}
    health = health_mod.HealthStore()
    swarm = swarm_rows.SwarmRowStore()
    stop = threading.Event()

    def poller() -> None:
        ticks, warned = 0, False
        while not stop.is_set():
            ticks += 1
            # re-discover real agents every ~2 s (60 ticks at 30 fps) so spawns appear, exits vanish
            if not fake and ticks % 60 == 0:
                try:
                    fresh, new_entries = _sources_for(root, fake)
                    refresh_sources(holder, model, fresh, new_entries, world)
                    model.prune()  # cards only: a lost-but-registered agent keeps its map track and event cursor
                except Exception:
                    if not warned:  # once: a persistent failure must not flood the log every 2 s
                        log.exception("agent re-discovery failed (further failures suppressed)")
                        warned = True
            model.poll(list(holder["sources"].values()))
            world.poll(list(holder["sources"].values()))
            if health_mod.poll_due(ticks, fps):   # <= 1 Hz: stalls/anomalies; invariants on a one-shot worker
                now = time.time()
                if fake:
                    health.fake_refresh(sorted(holder["sources"]), now)
                else:
                    health.refresh(root, now, health_mod.started_map(dict(holder["entries"])))
                health.request_invariants(root, now)
                swarm.refresh(root, model, holder["entries"], health)   # 1 Hz too: the swarm page's rows
            time.sleep(1.0 / fps)

    threading.Thread(target=poller, daemon=True).start()

    if web:
        from pokeagent.viewer import web as webview
        webview.serve_threaded(model, web_port)

    from pokeagent.viewer.ui.window import ViewerWindow
    from pokeagent.supervisor import Supervisor
    win = ViewerWindow(model, holder["sources"], fps=fps, supervisor=Supervisor(root),
                       root=root, world=world, health=health, swarm=swarm, stitched=stitched)
    win.entries = entries
    win.focus.set_mode(modes.internal("world" if world_mode else mode))
    try:
        win.run()
    finally:
        stop.set()
        for src in list(holder["sources"].values()):
            close_source(src)
        if stitched is not None:
            stitched.close()
    return 0


def _stitched_source(source, model: ViewerModel, game, preset, genre, fps: int | None = None,
                     refresh: float | None = None):
    """The stitched-map source when World mode's renderer is "stitched", else None."""
    if source is None:
        return None
    from pokeagent.mapview.presets import resolve
    from pokeagent.viewer import renderer_choice
    from pokeagent.viewer.stitched_source import StitchedSource
    p = resolve(game=game, preset=preset, genre=genre)
    if renderer_choice.choose(p, Path(source)) != renderer_choice.STITCHED:
        print(f"pokeagent view: --source {source} ignored: preset {p.name!r} uses the rom-world renderer "
              "(pick a stitched game/preset to use it)", file=sys.stderr)
        return None
    kw = {k: v for k, v in (("fps", fps), ("refresh", refresh)) if v is not None}
    st = StitchedSource(source, model, p, **kw)
    st.start()
    return st


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pokeagent view", description="Dear PyGui viewer for PokeAgent agents.")
    p.add_argument("--root", default=".", help="agent registry root (default: cwd)")
    p.add_argument("--fake", type=int, default=0, metavar="N", help="show N animated fake agents")
    p.add_argument("--web", action="store_true", help="also serve the read-only web view")
    p.add_argument("--port", type=int, default=8899, help="web view port (default 8899)")
    p.add_argument("--fps", type=int, default=30, help="poll/UI rate (default 30)")
    p.add_argument("--mode", choices=modes.CHOICES, default=modes.DEFAULT_MODE, help="start view (default world)")
    p.add_argument("--source", metavar="DIR", help="stitched map source (maps/ ghosts/ live/) for World mode")
    p.add_argument("--game", help="named game row of the preset table")
    p.add_argument("--preset", help="named view preset (wins over --game)")
    p.add_argument("--genre", help="named genre fallback when --game/--preset are absent")
    p.add_argument("--refresh", type=float, default=None, metavar="S",
                   help="stitched-map re-read cadence in seconds (default 2; needs --source)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return run(args.root, fps=args.fps, fake=args.fake, web=args.web, web_port=args.port, mode=args.mode,
               source=args.source, game=args.game, preset=args.preset, genre=args.genre,
               refresh=args.refresh)


if __name__ == "__main__":
    sys.exit(main())
