import numpy as np

from pokeagent.mapview.ghosts import Ghost
from pokeagent.mapview.playback import FPS, Clock, positions, tables


def ghost(run, n, every=2, area=0, x0=0.0):
    return Ghost(run, "a-" + run, "ok", every, np.full(n, area, np.int16),
                 x0 + np.arange(n, dtype=np.float32), np.full(n, 5.0, np.float32))


def test_positions_start_together_and_step_by_every():
    tb = tables([ghost("r1", 4, every=2), ghost("r2", 2, every=1, x0=100)], ["a-1"], FPS)
    f0 = positions(tb, 0.0)
    assert list(f0.idx) == [0, 0] and list(f0.xs) == [0, 100]       # all at their first point
    f = positions(tb, 3 * 2 / FPS)                                  # point 3 of an every=2 ghost
    assert list(f.idx) == [3, 1]                                    # the shorter one clamps
    assert f.xs[0] == 3 and f.xs[1] == 101


def test_position_at_exact_point_time_and_trail_start():
    tb = tables([ghost("r", 5, every=2)], ["a-1"], FPS)
    f = positions(tb, 2 * 2 / FPS)                                  # t = i * every / fps, i = 2
    assert f.idx[0] == 2 and f.xs[0] == 2 and f.trail_from[0] == 0


def test_finished_ghost_stays_at_its_last_point():
    tb = tables([ghost("r", 3, every=1)], ["a-1"], FPS)
    f = positions(tb, 10.0)
    assert f.idx[0] == 2 and f.xs[0] == 2 and f.finished[0]
    assert positions(tb, (3 - 1) * 1 / FPS - 0.001).finished[0] == False  # noqa: E712


def test_clock_loops_after_longest_plus_gap_and_speed_scales():
    c = Clock()
    c.duration = 1.0
    assert c.advance(0.5) is False and c.t == 0.5
    assert c.advance(2.1) is True and c.t == 0.0                    # past 1.0 + the 1.5 s gap
    c.speed = 2.0
    c.advance(0.5)
    assert c.t == 1.0                                               # twice as fast
    c.paused = True
    c.advance(0.5)
    assert c.t == 1.0                                               # paused holds the clock
