"""Pull-model poll cadences: per-source due logic on a fake clock (idle vs focused snapshot Hz,
an in-flight source skipped not queued, world /events focused vs idle), plus the 12-agent
per-tick call budget."""
import threading
import time

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.model import (FOCUS_FRAME_HZ, SNAPSHOT_HZ_FOCUS, SNAPSHOT_HZ_IDLE,
                                    ViewerModel)
from pokeagent.viewer.sources import FakeSource
from pokeagent.world.model import POLL_S_FOCUS, POLL_S_IDLE, WorldModel


class Counting(FakeSource):
    def __init__(self, aid):
        super().__init__(aid, [AgentSnapshot(agent_id=aid)], [(b"x", 1, 1)])
        self.snaps = self.frames = self.evts = 0

    def snapshot(self):
        self.snaps += 1
        return AgentSnapshot(agent_id=self.agent_id)

    def frame(self):
        self.frames += 1
        return (b"x", 1, 1)

    def events(self, since=0):
        self.evts += 1
        return {"events": []}


def test_idle_and_focused_snapshot_cadence():
    t = [0.0]
    m = ViewerModel(clock=lambda: t[0])
    a, b = Counting("a"), Counting("b")
    m.set_wants(focused="a")
    m.poll([a, b]); m.drain()
    assert (a.snaps, b.snaps) == (1, 1)                     # first tick: everything is due
    t[0] += 1.0 / SNAPSHOT_HZ_FOCUS + 0.01                  # focused is due again; idle is not
    m.poll([a, b]); m.drain()
    assert (a.snaps, b.snaps) == (2, 1)
    t[0] += 1.0 / SNAPSHOT_HZ_FOCUS + 0.01
    m.poll([a, b]); m.drain()
    assert (a.snaps, b.snaps) == (3, 1)
    t[0] += 1.0 / SNAPSHOT_HZ_IDLE                        # now the idle agent is due too
    m.poll([a, b]); m.drain()
    assert (a.snaps, b.snaps) == (4, 2) and a.snaps > b.snaps


def test_in_flight_source_is_skipped_not_queued():
    release = threading.Event()
    calls = []

    class Hung(FakeSource):
        def snapshot(self):
            calls.append(1)
            release.wait(5)
            return AgentSnapshot(agent_id=self.agent_id)

    m = ViewerModel()
    src = Hung("h")
    m.poll([src])
    end = time.monotonic() + 3
    while not calls and time.monotonic() < end:            # let the worker start the read
        time.sleep(0.005)
    m.poll([src])                                         # still in flight: skipped, not queued
    assert calls == [1]
    release.set()
    m.drain()
    assert m.snapshot("h") is not None


def test_world_events_focused_vs_idle_cadence():
    t = [0.0]
    wm = WorldModel(clock=lambda: t[0])
    a, b = Counting("a"), Counting("b")
    wm.set_focus("a")
    wm.poll([a, b]); wm.drain()
    assert (a.evts, b.evts) == (1, 1)
    t[0] += POLL_S_FOCUS + 0.01                           # focused due; idle gap not reached
    wm.poll([a, b]); wm.drain()
    assert (a.evts, b.evts) == (2, 1)
    t[0] += POLL_S_IDLE - POLL_S_FOCUS                    # idle due too
    wm.poll([a, b]); wm.drain()
    assert (a.evts, b.evts) == (3, 2)


def test_poll_budget_twelve_agents_one_tick():
    """One poll tick performs at most N source calls with 12 agents: N = 12 snapshots + the
    focused card's frame (13); in world mode with Stadium hidden the frame count is zero."""
    t = [0.0]
    m = ViewerModel(clock=lambda: t[0])
    srcs = [Counting(f"s{i}") for i in range(12)]
    m.set_wants(focused="s0", frames={})                   # nothing on screen -> no frame reads
    m.poll(srcs); m.drain()
    assert sum(s.snaps for s in srcs) == 12 and sum(s.frames for s in srcs) == 0
    for s in srcs:                                         # worst tick: every snapshot due + focus frame
        s.snaps = s.frames = 0
    m.set_wants(focused="s0", frames={"s0": FOCUS_FRAME_HZ})
    t[0] += 1.0 / SNAPSHOT_HZ_IDLE
    m.poll(srcs); m.drain()
    assert sum(s.snaps + s.frames for s in srcs) == 13
