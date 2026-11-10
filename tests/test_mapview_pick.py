"""Click-to-agent picking: pick_agent nearest/live-wins/None, and the click-vs-drag rule."""
import pytest

from pokeagent.mapview import pick


def test_pick_agent_nearest_within_radius():
    drawn = [("g1", "ghost", 50.0, 50.0), ("g2", "ghost", 80.0, 50.0)]
    assert pick.pick_agent(55.0, 50.0, drawn) == ("g1", "ghost")
    assert pick.pick_agent(75.0, 50.0, drawn) == ("g2", "ghost")
    assert pick.pick_agent(50.0, 59.9, drawn) == ("g1", "ghost")
    assert pick.pick_agent(50.0, 61.0, drawn) is None       # outside the 10 px radius
    assert pick.pick_agent(0.0, 0.0, []) is None


def test_live_wins_a_tie():
    drawn = [("g1", "ghost", 50.0, 50.0), ("a", "live", 50.0, 50.0)]
    assert pick.pick_agent(50.0, 50.0, drawn) == ("a", "live")


def test_is_click_within_4px():
    assert pick.is_click((10, 10), (13.9, 10))
    assert not pick.is_click((10, 10), (14.1, 10))
    assert not pick.is_click((10, 10), (10, 20))
    assert not pick.is_click(None, (10, 10))
    assert not pick.is_click((10, 10), None)


class _Win:
    """The slice of MapWindow pointer.release needs (no Dear PyGui calls)."""

    def __init__(self):
        self._down_at = None
        self._last_mouse = None
        self._drawn = [("g1", "ghost", 50.0, 50.0)]
        self.follow_best = False
        self.picked = []
        self.on_pick = lambda a, k: self.picked.append((a, k))

    def _set_follow_best(self, on):
        self.follow_best = on


def test_release_inside_slop_picks_and_reenables_follow(monkeypatch):
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.mapview import pointer
    win = _Win()
    win._down_at = (48.0, 50.0)                                   # press 2 px off the head
    monkeypatch.setattr(pointer, "mouse", lambda w: (50.0, 50.0))  # release on it
    pointer.release(win)
    assert win.picked == [("g1", "ghost")]
    assert win.follow_best                                        # a pick re-enables Follow selected


def test_release_after_a_drag_does_not_pick(monkeypatch):
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.mapview import pointer
    win = _Win()
    win._down_at = (20.0, 50.0)                                   # press 30 px away
    monkeypatch.setattr(pointer, "mouse", lambda w: (50.0, 50.0))
    pointer.release(win)
    assert win.picked == [] and not win.follow_best
