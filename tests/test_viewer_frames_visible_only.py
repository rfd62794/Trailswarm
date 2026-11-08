"""Frames only for what is on screen: the poller reads ``src.frame()`` only for the set the
views declared (``visible_frame_set``), at each card's own cadence; an empty set reads none."""
from types import SimpleNamespace

import pytest

from pokeagent.snapshot import AgentSnapshot
from pokeagent.viewer.model import CARD_FRAME_HZ, FOCUS_FRAME_HZ, ViewerModel
from pokeagent.viewer.sources import FakeSource
from pokeagent.viewer.ui.stadium_pane import FRAME_S


class Counting(FakeSource):
    def __init__(self, aid):
        super().__init__(aid, [AgentSnapshot(agent_id=aid)], [(b"x", 1, 1)])
        self.frames = 0

    def frame(self):
        self.frames += 1
        return (b"x", 1, 1)


def test_frames_read_only_for_the_visible_set():
    t = [0.0]
    m = ViewerModel(clock=lambda: t[0])
    srcs = {aid: Counting(aid) for aid in ("a", "b", "c")}
    m.set_wants(frames={"a": CARD_FRAME_HZ})               # only "a" has a card on screen
    m.poll(list(srcs.values())); m.drain()
    assert (srcs["a"].frames, srcs["b"].frames, srcs["c"].frames) == (1, 0, 0)
    assert m.frame("a") is not None and m.frame("b") is None


def test_no_frame_targets_means_zero_frame_reads():
    """World mode with the Stadium pane hidden: the visible set is empty -> no shm reads."""
    t = [0.0]
    m = ViewerModel(clock=lambda: t[0])
    srcs = [Counting(f"s{i}") for i in range(6)]
    m.set_wants(focused=None, frames={})
    m.poll(srcs); m.drain()
    assert all(s.frames == 0 for s in srcs)


def test_frame_cadence_follows_the_declared_hz():
    t = [0.0]
    m = ViewerModel(clock=lambda: t[0])
    s = Counting("a")
    m.set_wants(frames={"a": CARD_FRAME_HZ})
    m.poll([s]); m.drain()
    t[0] += 1.0 / CARD_FRAME_HZ / 2                        # not yet due
    m.poll([s]); m.drain()
    assert s.frames == 1
    t[0] += 1.0 / CARD_FRAME_HZ                            # now due
    m.poll([s]); m.drain()
    assert s.frames == 2


def test_window_visible_frame_set_matches_the_views():
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui.window import ViewerWindow
    win = ViewerWindow(ViewerModel(), {})
    assert win.visible_frame_set() == {}                   # nothing built/on screen yet
    win._grid = SimpleNamespace(cards={"a": 0, "b": 0})
    assert win.visible_frame_set() == {"a": CARD_FRAME_HZ, "b": CARD_FRAME_HZ}
    win.focus.set_mode("world")                            # grid hidden in world mode: no card frames
    assert win.visible_frame_set() == {}
    win._stadium = SimpleNamespace(slots=[SimpleNamespace(aid="s"), SimpleNamespace(aid=None)])
    assert win.visible_frame_set() == {"s": 1.0 / FRAME_S}  # the pane defaults to shown in world mode
    win.set_stadium_pref(True)
    win.focus.focus("c")                                   # focus + a stadium slot: max rate wins per agent
    assert win.visible_frame_set() == {"c": FOCUS_FRAME_HZ, "s": 1.0 / FRAME_S}
