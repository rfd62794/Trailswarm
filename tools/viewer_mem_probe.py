"""Headless memory probe for the World view's model/sources loop (no display, no ROM).

Runs N cycles of "an agent arrives, is polled by ViewerModel + WorldModel for a few ticks, exits" through the same
``refresh_sources`` the viewer uses, with a stubbed dpg standing in for the texture churn, then prints tracemalloc's top
growth and the cache sizes. Flat growth after the warm-up = no per-agent leak.

    PYTHONPATH=src uv run python tools/viewer_mem_probe.py --cycles 300 --top 12
"""
from __future__ import annotations

import argparse
import gc
import sys
import tracemalloc
import weakref
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.viewer import app  # noqa: E402
from pokeagent.viewer.model import ViewerModel  # noqa: E402
from pokeagent.world import events as ev  # noqa: E402
from pokeagent.world.model import WorldModel  # noqa: E402


class FakeAgent:
    """Enough of an HttpShmSource: events, a 160x144 frame, close()."""

    def __init__(self, aid: str) -> None:
        self.agent_id, self.closed, self._n, self._bus = aid, False, 0, ev.EventBus()

    def events(self, since: int = 0) -> dict:
        self._n += 1
        self._bus.emit(ev.Move(map=self._n % 4, x=self._n % 40, y=self._n % 30, facing="DOWN", step=self._n))
        return self._bus.payload(since)

    def snapshot(self):
        return None

    def frame(self):
        return bytes(160 * 144 * 3), 160, 144

    def close(self) -> None:
        self.closed = True


def cycle(i: int, model: ViewerModel, wm: WorldModel, holder: dict, ticks: int) -> FakeAgent:
    agent = FakeAgent(f"explore-{1000 + i}")
    app.refresh_sources(holder, model, {agent.agent_id: agent}, {agent.agent_id: {"id": agent.agent_id}}, wm)
    srcs = list(holder["sources"].values())
    model.set_wants(None, {agent.agent_id: 10.0})
    for _ in range(ticks):
        model.poll(srcs)
        wm.poll(srcs)
        model.drain()
        wm.drain()
        model._snap_at.clear(); model._frame_at.clear(); wm._polled.clear()    # every tick is "due"
        wm.tracks(); wm.feed()
    return agent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cycles", type=int, default=200, help="agents that arrive and leave")
    ap.add_argument("--ticks", type=int, default=20, help="poll ticks per agent")
    ap.add_argument("--warmup", type=int, default=20, help="cycles before the baseline snapshot")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    model, wm, holder = ViewerModel(), WorldModel(), {"sources": {}, "entries": {}}
    tracemalloc.start(25)
    made = weakref.WeakSet()   # the probe itself must not keep agents alive
    opened = 0
    for i in range(a.warmup):
        made.add(cycle(i, model, wm, holder, a.ticks)); opened += 1
    gc.collect()
    base, base_cur = tracemalloc.take_snapshot(), tracemalloc.get_traced_memory()[0]
    for i in range(a.warmup, a.warmup + a.cycles):
        made.add(cycle(i, model, wm, holder, a.ticks)); opened += 1
    app.refresh_sources(holder, model, {}, {}, wm)
    app.refresh_sources(holder, model, {}, {}, wm)
    gc.collect()
    snap, cur = tracemalloc.take_snapshot(), tracemalloc.get_traced_memory()[0]
    print(f"{a.cycles} agents arrived and left after a {a.warmup}-agent warm-up")
    print(f"traced memory: {base_cur / 1e6:.2f} MB -> {cur / 1e6:.2f} MB  (growth {(cur - base_cur) / 1e6:+.3f} MB, "
          f"{(cur - base_cur) / a.cycles / 1e3:+.2f} KB per agent)")
    print(f"sources still alive: {len(made)} (and not closed: {sum(not m.closed for m in made)}) of {opened} created")
    print(f"caches: viewer snap={len(model._snap)} frame={len(model._frame)} ids={len(model.ids())} | world tracks={len(wm._tracks)} "
          f"since={len(wm._since)} polled={len(wm._polled)} feed={len(wm._feed)}")
    print(f"top {a.top} growth by line:")
    for st in snap.compare_to(base, "lineno")[:a.top]:
        print("  ", st)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
