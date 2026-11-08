import time
from pathlib import Path

import numpy as np

from pokeagent.mapview.areas import Area
from pokeagent.mapview.ghosts import Ghost
from pokeagent.mapview.layout import place
from pokeagent.mapview.overlay import PALETTE, color_index, render
from pokeagent.mapview.playback import FPS, positions, tables


def ghost(run="r1", agent="w-1", n=10, every=2, outcome="ok", area=0, x0=10.0, y=5.0):
    return Ghost(run, agent, outcome, every, np.full(n, area, np.int16),
                 x0 + np.arange(n, dtype=np.float32), np.full(n, y, np.float32))


def scene(ghosts, names=("a-1",), w=400, h=60):
    tb = tables(ghosts, names, FPS)
    lay = place([Area("a-1", w, h, 1.0, Path("a.png"))], max_row_width=1000)
    return tb, lay


def test_render_returns_exactly_the_visible_rect_size():
    tb, lay = scene([ghost()])
    f = positions(tb, 0.0)
    out = render(f, tb, lay, (0, 0, 200, 100), zoom=0.5)
    assert out.shape == (50, 100, 4) and out.dtype == np.uint8      # screen rect, not the space
    assert render(f, tb, lay, (0, 0, 200, 100), zoom=1.0).shape == (100, 200, 4)


def test_head_at_the_expected_pixel():
    tb, lay = scene([ghost(n=1, x0=10.0, y=5.0)])
    out = render(positions(tb, 0.0), tb, lay, (0, 0, 100, 100), zoom=1.0, trails=False)
    rgb = PALETTE[color_index("w-1", len(PALETTE))]
    assert list(out[25, 10, :3]) == list(rgb) and out[25, 10, 3] == 255   # offset (0,20) + (10,5)
    assert out[0, 0, 3] == 0                                        # empty corner stays clear


def test_death_mark_only_after_a_death_outcome_finishes():
    tb, lay = scene([ghost(outcome="death", n=5, x0=30.0, y=5.0)])
    early = render(positions(tb, 0.0), tb, lay, (0, 0, 120, 80), zoom=1.0, trails=False)
    marked = (early[..., :3] == [225, 45, 45]).all(-1)
    assert not marked.any()                                         # alive: no mark yet
    late = render(positions(tb, 4 * 2 / FPS + 0.5), tb, lay, (0, 0, 120, 80),
                  zoom=1.0, trails=False)
    marked = (late[..., :3] == [225, 45, 45]).all(-1)
    x, y = 34, 25                                                   # last point (30+4, 20+5)
    assert marked[y, x] and marked[y, x - 2] and marked[y - 2, x]   # a cross at the last point
    off = render(positions(tb, 4 * 2 / FPS + 0.5), tb, lay, (0, 0, 120, 80),
                 zoom=1.0, trails=False, show_marks=False)
    assert not (off[..., :3] == [225, 45, 45]).all(-1).any()        # the toggle hides them


def test_finished_non_death_outcome_marks_nothing():
    tb, lay = scene([ghost(outcome="best", n=3)])
    out = render(positions(tb, 10.0), tb, lay, (0, 0, 120, 80), zoom=1.0, trails=False)
    assert not (out[..., :3] == [225, 45, 45]).all(-1).any()


def test_ghost_in_an_area_the_layout_lacks_draws_nothing():
    g = Ghost("r1", "w", "death", 2, np.full(5, -1, np.int16),
              np.arange(5, dtype=np.float32), np.ones(5, np.float32))
    tb = tables([g], ["a-1"], FPS)
    lay = place([Area("a-1", 100, 40, 1.0, Path("a.png"))])
    out = render(positions(tb, 5.0), tb, lay, (0, 0, 100, 80), zoom=1.0)
    assert not out[..., 3].any()                                    # skipped silently


def test_best_ghost_drawn_white_with_a_dark_edge():
    g1 = ghost("r1", "w-1", n=5, x0=20.0)
    g2 = ghost("r2", "w-2", n=5, x0=60.0)
    tb, lay = scene([g1, g2])
    out = render(positions(tb, 0.0), tb, lay, (0, 0, 150, 80), zoom=1.0, trails=False, best=1)
    assert list(out[25, 60, :3]) == [255, 255, 255]                 # head centre is white
    assert list(out[25, 58, :3]) == [25, 25, 25]                    # one-pixel dark outline


def test_display_cost_is_flat_as_ghosts_grow():
    tb5, lay = scene([ghost(f"r{k}", f"w-{k % 3}", n=20) for k in range(5)])
    tb60, _ = scene([ghost(f"r{k}", f"w-{k % 7}", n=20) for k in range(60)])
    rect, zoom = (0, 0, 300, 200), 0.5

    def clocked(tb):
        f = positions(tb, 0.5)
        best = None
        for _ in range(3):                                          # best of 3 rounds of 5 calls
            t0 = time.perf_counter()
            for _ in range(5):
                render(f, tb, lay, rect, zoom)
            dt = (time.perf_counter() - t0) / 5
            best = dt if best is None else min(best, dt)
        return best

    assert clocked(tb60) < 3 * clocked(tb5)                         # the cost is not per ghost


def test_ghosts_with_no_areas_render_empty_not_raise():
    tb = tables([ghost()], (), FPS)
    lay = place([], max_row_width=1000)
    out = render(positions(tb, 0.1), tb, lay, (0, 0, 50, 20), 1.0)
    assert out.shape == (20, 50, 4) and not out.any()


def test_non_finite_square_is_skipped():
    from pokeagent.mapview.overlay import _square
    out = np.zeros((5, 5, 4), np.uint8)
    _square(out, float("nan"), 2.0, 3, np.array([1, 2, 3], np.uint8))
    assert not out.any()
