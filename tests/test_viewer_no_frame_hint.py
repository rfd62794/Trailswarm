"""A tile with a snapshot but no frame says why, instead of a blank (headless: no window, no dpg)."""
from pokeagent.viewer.panels.noframe import NO_FRAME_HINT, hint_lines, hint_texture


def test_hint_text_names_the_flag():
    assert NO_FRAME_HINT == "no frame - swarm started with --no-share-frames"
    joined = " ".join(t for line in hint_lines(20) for t, _ in line)
    assert "no frame" in joined and "--no-share-frames" in joined


def test_hint_texture_has_requested_size_at_supersample():
    data, tw, th = hint_texture(80, 60)
    assert len(data) == tw * th * 4 and (tw, th) == (160, 120)   # lines_texture supersamples 2x


def test_card_update_draws_hint_when_snapshot_but_no_frame(monkeypatch):
    import pytest
    pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.ui import card as cardmod
    from test_viewer_agents import snap
    seen = {}
    monkeypatch.setattr(cardmod, "hint_texture", lambda w, h: _fake(seen, w, h))
    c = cardmod.CardView.__new__(cardmod.CardView)
    # exercise only the top-strip branch via a stub: sizes + memo + textures
    class Tex:
        def set(self, data, w, h, key): seen["set"] = (w, h); return "t"
    c._sizes, c._split, c._memo, c._top_at = {"top": (40, 30), "header": (1, 1)}, (40, 40), {}, 0.0
    c._sees_cache, c._tex, c._img = (None, None), {"top": Tex()}, {"top": 1}
    monkeypatch.setattr(cardmod.dpg, "configure_item", lambda *a, **k: None)
    c.update(snap("a1"), None, "live")
    assert seen["hint"] == (40, 30)


def _fake(seen, w, h):
    import numpy as np
    seen["hint"] = (w, h)
    return np.zeros(w * 2 * h * 2 * 4, dtype=np.float32), w * 2, h * 2
