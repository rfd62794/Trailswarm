import pytest

from pokeagent.viewer import ui_scale as u
from pokeagent.viewer.screen_fit import viewport_size
from pokeagent.world import zoom
from pokeagent.world.view import Viewport


def test_scale_from_dpi_and_override():
    assert u.scale_from_dpi(120) == 1.25 and u.scale_from_dpi(96) == 1.0
    assert u.effective_scale(120, {}) == 1.25
    assert u.effective_scale(None, {}) == 1.0
    assert u.effective_scale(120, {"POKEAGENT_UI_SCALE": "1.5"}) == 1.5
    assert u.effective_scale(120, {"POKEAGENT_UI_SCALE": "junk"}) == 1.25
    assert u.effective_scale(96, {"POKEAGENT_UI_SCALE": "99"}) == u.MAX_SCALE


def test_px_scales_fixed_sizes():
    assert u.px(120, 1.25) == 150 and u.px(44, 1.0) == 44


def test_viewport_physical_px():
    # 1920x1080 @125%: physical work area ~1920x1040, window is the scaled default and fits
    w, h = viewport_size((1920, 1040), 1.25)
    assert w == 1875 and h <= 1040 - 60 and h > 900
    # 2560x1440 @100%: unchanged defaults
    assert viewport_size((2560, 1400), 1.0) == (1500, 950)
    assert viewport_size(None, 1.25) == (1875, 1188)


def test_side_panel_proportional_and_clamped():
    assert u.side_panel_width(1000, 1.0) == 260
    assert u.side_panel_width(1500, 1.0) == 330
    assert u.side_panel_width(3000, 1.0) == 420
    assert u.side_panel_width(1875, 1.25) == int(1875 * 0.22)


def test_min_sprite_size():
    assert u.sprite_px(0.1, 9, 13, 1.0) == 13
    assert u.sprite_px(0.1, 9, 13, 2.0) == 26
    assert u.sprite_px(4.0, 9, 13, 1.0) == 36


def test_zoom_snapping():
    assert zoom.step(1.0, 1) == 2.0 and zoom.step(1.0, -1) == 0.5
    assert zoom.step(1.25, 1) == 2.0 and zoom.step(1.25, -1) == 1.0
    assert zoom.step(8.0, 1) == 8.0 and zoom.step(0.125, -1) == 0.125
    assert zoom.fit_snap(2000, 2000, 1100, 800) == 0.25
    assert zoom.fit_snap(20000, 20000, 1100, 800) == pytest.approx(0.04)  # nothing fits: exact


def test_viewport_fit_resize_and_one_to_one():
    vp = Viewport(2000, 2000, 1100, 800)
    vp.fit()
    assert vp.zoom == 0.25
    vp.resize(2000, 1500)                     # untouched view re-fits
    assert vp.zoom == 0.5 and (vp.cx, vp.cy) == (1000, 1000)
    vp.pan(30, 0)
    cx = vp.cx
    vp.resize(900, 700)                       # touched view keeps its centre
    assert vp.cx == cx
    vp.one_to_one(1.25)
    assert vp.zoom == 1.25
    vp.step_zoom_at(450, 350, 1)
    assert vp.zoom == 2.0
