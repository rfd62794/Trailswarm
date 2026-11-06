from pokeagent.viewer.screen_fit import DEFAULT_H, DEFAULT_W, viewport_size


def test_fits_inside_a_small_work_area():
    w, h = viewport_size((1536, 864))
    assert w <= 1536 - 24 and h <= 864 - 48


def test_defaults_on_a_big_screen_or_unknown():
    assert viewport_size((2560, 1400)) == (DEFAULT_W, DEFAULT_H)
    assert viewport_size(None) == (DEFAULT_W, DEFAULT_H)
