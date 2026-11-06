"""``pokeagent view``: discover agents, poll the model in a thread, draw the Dear PyGui window.

``run(root, fps=30)`` is the entry point; ``--fake N`` swaps discovery for animated synthetic
agents (demos/tests). ``--web`` additionally serves the read-only page on 127.0.0.1.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from pokeagent.agent_registry import list_agents
from pokeagent.snapshot import AgentSnapshot, Goal, Screen, Sees, Segment, Thinking
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.sources import AgentSource, HttpShmSource, discover

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

    def send(self, cmd: str, **args) -> dict:
        return self._src.send(cmd, **args)


class _AnimatedFake:
    """Synthetic agent for --fake: snapshot/frame change every poll; send() records commands."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._t = 0
        self.sent: list[tuple[str, dict]] = []

    def snapshot(self) -> AgentSnapshot:
        self._t += 1
        t = self._t
        glyphs = "@NTo#o~!W"
        rows = ["".join(glyphs[(i * 7 + t + j) % len(glyphs)] for j in range(10)) for i in range(9)]
        return AgentSnapshot(
            agent_id=self.agent_id, kind="explorer" if t % 2 else "rl", state="running",
            step=t, segment=Segment(id="S3", name="first_pokemon", status="current", steps=3),
            goals=[Goal(id="g1", name="first_pokemon", status="current", steps=3)],
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
        px = bytearray(w * h * 3)
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 3
                px[i] = (x * 3 + t) % 256
                px[i + 1] = (y * 5 + t * 2) % 256
                px[i + 2] = ((x + y) * 2 + t) % 256
        return bytes(px), w, h

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


def run(root, fps: int = 30, fake: int = 0, web: bool = False, web_port: int = 8899) -> int:
    root = Path(root)
    sources, entries = _sources_for(root, fake)
    model = ViewerModel()
    holder = {"sources": {aid: _Throttle(s) for aid, s in sources.items()}, "entries": entries}
    stop = threading.Event()

    def poller() -> None:
        ticks = 0
        while not stop.is_set():
            ticks += 1
            # re-discover real agents every ~2 s (60 ticks at 30 fps) so spawns appear, exits vanish
            if not fake and ticks % 60 == 0:
                try:
                    fresh, new_entries = _sources_for(root, fake)
                    holder["sources"].clear()
                    holder["sources"].update({aid: _Throttle(s) for aid, s in fresh.values()})
                    holder["entries"].clear()
                    holder["entries"].update(new_entries)
                    model.prune()
                except Exception:
                    pass
            model.poll(list(holder["sources"].values()))
            time.sleep(1.0 / fps)

    threading.Thread(target=poller, daemon=True).start()

    if web:
        from pokeagent.viewer import web as webview
        webview.serve_threaded(model, web_port)

    from pokeagent.viewer.ui.window import ViewerWindow
    from pokeagent.supervisor import Supervisor
    win = ViewerWindow(model, holder["sources"], fps=fps, supervisor=Supervisor(root),
                       root=root)
    win.entries = entries
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
    return run(args.root, fps=args.fps, fake=args.fake, web=args.web, web_port=args.port)


if __name__ == "__main__":
    sys.exit(main())
