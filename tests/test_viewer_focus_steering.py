"""Focus-only steering: grid keys reach nobody; focus steers the focused agent; leaving releases."""
import pytest

from pokeagent.viewer.sources import FakeSource
from pokeagent.viewer.steering import KeyThrottle, press_target
from test_viewer_agents import FRAME, snap


def test_grid_keys_reach_nobody():
    assert press_target("Up", None, KeyThrottle()) is None


def test_focus_maps_keys_to_focused_agent():
    t = KeyThrottle()
    assert press_target("Up", "a", t) == ("a", "UP")
    assert press_target("Return", "a", t) == ("a", "START")
    assert press_target("Shift_L", "a", t) == ("a", "SELECT")
    assert press_target("z", "a", t) is None


def test_throttle_one_press_per_120ms_per_key():
    now = [0.0]
    t = KeyThrottle(clock=lambda: now[0])
    assert t.allow("Up")
    now[0] = 0.05
    assert not t.allow("Up") and t.allow("Down")
    now[0] = 0.13
    assert t.allow("Up")


@pytest.fixture
def win():
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    model = ViewerModel()
    srcs = {i: FakeSource(i, [snap(i)], [FRAME]) for i in ("a", "b")}
    model.poll(list(srcs.values()))
    return ViewerWindow(model, srcs), srcs


def _cmds(srcs, aid):
    return [c for c, _ in srcs[aid].sent]


def test_window_grid_keys_ignored_even_when_selected(win):
    w, srcs = win
    w.selected = "a"
    w.key_button("Up")
    w.flush_sends()
    assert _cmds(srcs, "a") == []


def test_window_focus_steers_then_release_on_leave(win):
    w, srcs = win
    w.selected = "b"                       # selection is irrelevant in focus
    w.toggle_focus("a")                    # double-click
    w.key_button("Up")
    w.send_to_targets("pause")             # control bar acts on the focused agent only
    w.flush_sends()
    assert _cmds(srcs, "a") == ["steer", "press", "pause"] and _cmds(srcs, "b") == []
    assert srcs["a"].sent[1][1] == {"button": "UP", "source": "human"}
    w.leave_focus()                        # < All agents / Esc
    w.flush_sends()
    assert _cmds(srcs, "a")[-2:] == ["hold_release", "steer"] and srcs["a"].sent[-1][1] == {"on": False}
    w.key_button("Up")
    w.flush_sends()
    assert _cmds(srcs, "a").count("press") == 1


def test_double_click_again_leaves_focus(win):
    w, srcs = win
    w.toggle_focus("a")
    w.toggle_focus("a")
    w.flush_sends()
    assert w.focus.focused is None and _cmds(srcs, "a")[-2:] == ["hold_release", "steer"]
