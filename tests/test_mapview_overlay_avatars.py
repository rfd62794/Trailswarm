"""overlay.render with an avatar source: stamped pictures, the live ring, flat cost."""
import time
from pathlib import Path

import numpy as np

from pokeagent.mapview.areas import Area
from pokeagent.mapview.ghosts import Ghost
from pokeagent.mapview.layout import place
from pokeagent.mapview.overlay import PALETTE, color_index, render
from pokeagent.mapview.playback import FPS, positions, tables

AV_RGB = (9, 111, 42)


def avatar_img(size=8):
    img = np.zeros((size, size, 4), np.uint8)
    img[1:-1, 1:-1, :3] = AV_RGB
    img[1:-1, 1:-1, 3] = 255
    return img


class FakeAvatars:
    def __init__(self, img=None):
        self.img, self.calls = img, []

    def get(self, agent, facing, phase, colour):
        self.calls.append(agent)
        return self.img


def ghost(run="r1", agent="w-1", n=10, every=2, outcome="ok", area=0, x0=10.0, y=5.0):
    return Ghost(run, agent, outcome, every, np.full(n, area, np.int16),
                 x0 + np.arange(n, dtype=np.float32), np.full(n, y, np.float32))


def scene(ghosts, names=("a-1",), w=400, h=60):
    tb = tables(ghosts, names, FPS)
    lay = place([Area("a-1", w, h, 1.0, Path("a.png"))], max_row_width=1000)
    return tb, lay


def test_avatar_drawn_where_the_head_was():
    tb, lay = scene([ghost(n=1, x0=10.0, y=5.0)])                          # head at space (10, 25)
    av = FakeAvatars(avatar_img())
    out = render(positions(tb, 0.0), tb, lay, (0, 0, 100, 100), 1.0, trails=False,
                 avatars=av, avatar_size=8)
    rgb = PALETTE[color_index("w-1", len(PALETTE))]
    assert list(out[25, 10, :3]) == list(AV_RGB) and out[25, 10, 3] == 255
    assert not (out[..., :3] == rgb).all(-1).any()                        # the square was not drawn
    assert av.calls == ["w-1"]                                            # asked once for the one head


def test_empty_cache_falls_back_to_the_square():
    tb, lay = scene([ghost(n=1, x0=10.0, y=5.0)])
    out = render(positions(tb, 0.0), tb, lay, (0, 0, 100, 100), 1.0, trails=False,
                 avatars=FakeAvatars(None))
    rgb = PALETTE[color_index("w-1", len(PALETTE))]
    assert list(out[25, 10, :3]) == list(rgb) and out[25, 10, 3] == 255   # square as before


def test_live_agent_gets_a_white_ring_ghosts_do_not():
    g = ghost("r1", "w-1", n=1, x0=60.0, y=5.0)
    tb, lay = scene([g])
    av = FakeAvatars(avatar_img())
    live = [("w-live", 30.0, 25.0, "RIGHT", 0)]                           # space coords: offset (0,20)+(30,5)
    out = render(positions(tb, 0.0), tb, lay, (0, 0, 120, 80), 1.0, trails=False,
                 avatars=av, avatar_size=8, live=live)
    assert (out[20, 25:35, :3] == [255, 255, 255]).all()                  # ring top row is white
    assert not (out[20, 55:65, :3] == [255, 255, 255]).all()              # the ghost has no ring
    ghost2 = render(positions(tb, 0.0), tb, lay, (0, 0, 120, 80), 1.0, trails=False,
                    avatars=FakeAvatars(None), live=live)
    rgb = PALETTE[color_index("w-live", len(PALETTE))]
    assert list(ghost2[25, 30, :3]) == list(rgb)                          # live square fallback
    assert (ghost2[22, 28:33, :3] == [255, 255, 255]).all()               # white ring around it


def test_ghost_and_live_outside_the_rect_draw_nothing():
    tb, lay = scene([ghost(n=1, x0=900.0, y=5.0)])
    out = render(positions(tb, 0.0), tb, lay, (0, 0, 100, 60), 1.0, trails=False,
                 avatars=FakeAvatars(avatar_img()), live=[("w-live", 900.0, 25.0, "RIGHT", 0)])
    assert not out[..., 3].any()


def test_render_shape_stays_the_visible_rect_with_avatars():
    tb, lay = scene([ghost()])
    out = render(positions(tb, 0.5), tb, lay, (0, 0, 200, 100), 0.5,
                 avatars=FakeAvatars(avatar_img()))
    assert out.shape == (50, 100, 4)


def test_display_cost_flat_as_ghosts_grow_with_avatars():
    tb5, lay = scene([ghost(f"r{k}", f"w-{k % 3}", n=20) for k in range(5)])
    tb60, _ = scene([ghost(f"r{k}", f"w-{k % 7}", n=20) for k in range(60)])
    rect, zoom = (0, 0, 300, 200), 0.5
    av = FakeAvatars(avatar_img())

    def clocked(tb):
        f = positions(tb, 0.5)
        best = None
        for _ in range(3):
            t0 = time.perf_counter()
            for _ in range(5):
                render(f, tb, lay, rect, zoom, avatars=av)
            dt = (time.perf_counter() - t0) / 5
            best = dt if best is None else min(best, dt)
        return best

    assert clocked(tb60) < 3 * clocked(tb5)
