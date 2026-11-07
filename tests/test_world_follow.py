import pytest

from pokeagent.world.follow import EASE_PER_S, LOST_AFTER_S, SNAP_PX, Follow
from pokeagent.world.view import Viewport


def test_start_then_target_returns_the_agents_point():
    f = Follow()
    assert not f.active
    f.start("agent-1", 10.0)
    assert f.active
    assert f.target({"agent-1": (100.0, 200.0), "agent-2": (0.0, 0.0)}, 10.5) == (100.0, 200.0)
    assert f.last_seen == 10.5


def test_missing_agent_stops_only_after_lost_after_s():
    f = Follow()
    f.start("a", 0.0)
    assert f.target({}, LOST_AFTER_S - 1.0) is None          # briefly missing: still following, no crash
    assert f.active
    assert f.target({}, LOST_AFTER_S + 1.0) is None          # gone too long: give up
    assert not f.active and f.agent_id is None


def test_stop_clears_the_follow():
    f = Follow()
    f.start("a", 0.0)
    f.stop()
    assert not f.active and f.target({"a": (1.0, 2.0)}, 0.1) is None


def test_step_eases_never_overshoots_and_keeps_zoom():
    vp = Viewport(world_w=4000, world_h=4000)
    vp.cx, vp.cy, vp.zoom = 1000.0, 1000.0, 0.5
    f = Follow()
    f.step(vp, (1100.0, 1200.0), 0.05)                       # 0.05 * 8 = 40% of the gap
    assert vp.cx == pytest.approx(1000.0 + 100.0 * 0.05 * EASE_PER_S)
    assert vp.cy == pytest.approx(1000.0 + 200.0 * 0.05 * EASE_PER_S)
    assert vp.zoom == 0.5
    f.step(vp, (1100.0, 1200.0), 10.0)                       # huge dt clamps to the whole gap: lands exactly
    assert (vp.cx, vp.cy) == pytest.approx((1100.0, 1200.0))
    assert vp.zoom == 0.5


def test_step_snaps_when_the_gap_is_past_snap_px():
    vp = Viewport(world_w=4000, world_h=4000)
    vp.cx, vp.cy = 0.0, 0.0
    Follow().step(vp, (0.0, SNAP_PX + 100.0), 0.0)
    assert (vp.cx, vp.cy) == (0.0, SNAP_PX + 100.0)


def test_step_leaves_auto_fit_false():
    vp = Viewport(world_w=4000, world_h=4000)
    assert vp.auto_fit
    Follow().step(vp, (1500.0, 1500.0), 0.05)
    assert vp.auto_fit is False
