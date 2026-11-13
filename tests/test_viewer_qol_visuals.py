"""Pure pieces of the viewer QoL / visuals work: label pill, agent colours, health ring, steps text, tidy names, layers legend,
minimap maths, screenshot path, palette tint, roster. No ROM, no display."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from pokeagent.snapshot import AgentSnapshot, Goal, PartyMon, Screen, Segment
from pokeagent.viewer import roster, screenshot
from pokeagent.viewer.health import ANOMALY, OK, SLOW, STALLED, ring_alpha, ring_colour
from pokeagent.viewer.panels import steps
from pokeagent.viewer.theme_colours import palette, toggle
from pokeagent.viewer.ui_scale import window_scale
from pokeagent.world import layers, names, pill
from pokeagent.world.minimap import MiniMap
from pokeagent.world.model import Track
from pokeagent.world.palette import AGENT_COLOURS, GB_GREENS, agent_colour, gb_tint


def test_pill_sits_above_the_sprite_and_scales_with_zoom():
    a, b = pill.pill(100, 50, 40, 11, 1.0), pill.pill(100, 50, 40, 11, 4.0)
    assert a.y1 < 50 and a.x0 < 100 < a.x1                    # above the sprite top, centred
    assert abs((a.x0 + a.x1) / 2 - 100) < 1e-6
    assert a.radius == (a.y1 - a.y0) / 2                      # full capsule
    assert a.text_x > a.x0 and a.text_y > a.y0
    assert (b.x1 - b.x0) > (a.x1 - a.x0)                      # bigger when zoomed in ...
    far = pill.pill(100, 50, 40, 11, 0.01)
    assert (far.x1 - far.x0) >= (a.x1 - a.x0) * pill.MIN_K * 0.99   # ... but never unreadably small
    assert (pill.pill(0, 0, 40, 11, 100).x1 - pill.pill(0, 0, 40, 11, 100).x0) <= (a.x1 - a.x0) * pill.MAX_K * 1.01


def test_agent_colour_is_stable_and_distinct():
    ids = [f"agent-{i}" for i in range(1, 6)]
    cols = [agent_colour(i) for i in ids]
    assert len(set(cols)) == 5 and all(c in AGENT_COLOURS for c in cols)
    assert agent_colour("agent-3", ids) == agent_colour("agent-3", ids[:2]) == agent_colour("agent-3")   # independent of who else runs
    assert agent_colour("gen#1") == agent_colour("gen#1") and agent_colour("explorer-main") in AGENT_COLOURS


def test_stalled_state_maps_to_the_ring_colour():
    base = agent_colour("agent-1")
    assert ring_colour(OK, base) == base
    assert ring_colour(STALLED, base) == (255, 60, 60) and ring_colour(SLOW, base) != base and ring_colour(ANOMALY, base) != base
    assert ring_alpha(OK, 0.3) == 255 and ring_alpha(SLOW, 0.3) == 255
    alphas = {ring_alpha(STALLED, t / 20) for t in range(20)}
    assert min(alphas) < 120 and max(alphas) > 240            # it pulses


def snap(**kw) -> AgentSnapshot:
    return AgentSnapshot(agent_id="a", **kw)


def test_steps_vs_best_text_and_sparkline():
    s = snap(goals=[Goal("g1", "oak_parcel", "done", 300), Goal("g2", "beat_misty", "current")], segment=Segment("S2", "beat_misty", 1240, 980))
    assert steps.steps_text(s) == "beat_misty: 1,240 steps (best 980)"
    assert steps.steps_text(snap(segment=Segment("x", "", 5, None))) == "x: 5 steps (no record yet)"
    assert steps.goal_steps(s) == [300, 1240]
    sp = steps.sparkline([300, 1240, 620])
    assert len(sp) == 3 and sp[1] == "#" and steps._LEVELS.index(sp[0]) < steps._LEVELS.index(sp[1]) and steps.sparkline([]) == ""


def test_tidy_names_and_no_overlap():
    assert names.tidy_name("0x3E CERULEAN_TRASHED_HOUSE") == "Cerulean Trashed House"
    assert names.tidy_name("CERULEAN_POKECENTER") == "Cerulean Pokecenter"
    assert names.tidy_name("MR_FUJIS_HOUSE") == "Mr Fujis House"
    col = names.column_px(4)
    assert col == (4 + 2) * 16 - 4
    for raw in ("0x3E CERULEAN_TRASHED_HOUSE", "VIRIDIAN_POKECENTER", "A"):
        txt = names.label_for(raw, col)
        assert len(txt) * 6 <= col and "0x" not in txt        # fits its column, no hex ids
    assert names.label_for("CERULEAN_TRASHED_HOUSE", 60).endswith("..")
    assert names.label_for("OAKS_LAB", 400) == "Oaks Lab"


def test_labels_in_a_row_stay_inside_their_columns():
    from pokeagent.atlas.world import CELL, GAP
    widths = [4, 6, 8, 4]
    x, edges = 0, []
    for w in widths:
        edges.append((x * CELL, x * CELL + len(names.label_for("CERULEAN_TRASHED_HOUSE", names.column_px(w))) * 6))
        x += w + GAP
    nxt = [e[0] for e in edges][1:]
    assert all(end <= start for (_s, end), start in zip(edges, nxt))


def test_layers_have_data_or_show_the_empty_legend():
    model = {"maps": {"0": {"visited": {"1,1": 3}, "blocked": ["1,1,UP"], "warps": {}}}}
    assert layers.has_data(model, ("heat", "walls")) and layers.has_data(model, ("walls",))
    assert not layers.has_data(model, ("warps",)) and not layers.has_data({}, ("heat",))
    assert layers.legend_lines(("heat",), model) == []
    lg = layers.legend_lines(("heat", "walls"), {})
    assert lg[0] == "no learning data" and "heat, walls" in lg[1]
    assert layers.legend_lines((), {}) == []


def test_empty_layers_export_differs_from_none_and_data_layers_draw():
    from pokeagent.atlas.world import Place, WorldLayout
    from pokeagent.world.draw import SpriteBook, render_state
    from test_world_view import synth_rom
    lay = WorldLayout({0: Place(2, 3, 10, 9, False)}, 30, 14, 14)
    base = np.full((lay.size_px[1], lay.size_px[0], 3), 120, dtype=np.uint8)
    book = SpriteBook(synth_rom())
    plain = render_state(base, lay, [], book, 1.0)
    empty = render_state(base, lay, [], book, 1.0, {}, {}, ("heat", "walls"))
    assert (plain != empty).any()                                          # the legend is drawn, not a silent no-op
    full = render_state(base, lay, [], book, 1.0, {"maps": {"0": {"visited": {"1,1": 5}}}}, {}, ("heat",))
    assert (plain != full).any() and not (full[12:60, 12:300] != empty[12:60, 12:300]).all()


def test_load_model_tolerates_missing_and_junk(tmp_path):
    assert layers.load_model(tmp_path / "none.json") == {}
    (tmp_path / "m.json").write_text("{not json")
    assert layers.load_model(tmp_path / "m.json") == {}
    (tmp_path / "ok.json").write_text('{"maps": {"0": {"visited": {"1,1": 1}}}}')
    assert layers.has_data(layers.load_model(tmp_path / "ok.json"), ("heat",))


def test_minimap_viewport_rect_and_click_maths():
    mm = MiniMap(2000, 1000, 200, 160)
    assert mm.scale == 0.1 and mm.size == (200.0, 100.0)
    assert mm.viewport_rect((500, 200, 900, 600)) == (50.0, 20.0, 90.0, 60.0)
    assert mm.viewport_rect((-100, -100, 5000, 5000)) == (0.0, 0.0, 200.0, 100.0)    # clipped to the box
    assert mm.to_world(50, 20) == (500.0, 200.0) and mm.to_world(999, 999) == (2000.0, 1000.0)
    assert mm.contains(10, 10) and not mm.contains(10, 120) and not mm.contains(-1, 5)
    assert mm.agent_dot(1000, 500) == (100.0, 50.0)


def test_minimap_round_trip_with_the_viewport():
    from pokeagent.world.view import Viewport
    vp = Viewport(2000, 1000, 400, 300, zoom=1.0)
    mm = MiniMap(2000, 1000, 200, 160)
    vp.center_on(*mm.to_world(100, 50))                                    # click the middle of the minimap
    assert (vp.cx, vp.cy) == (1000.0, 500.0)
    x0, y0, x1, y1 = mm.viewport_rect(vp.visible())
    assert abs((x0 + x1) / 2 - 100) < 1e-6 and abs((y0 + y1) / 2 - 50) < 1e-6


def test_screenshot_path(tmp_path):
    p = screenshot.screenshot_path(tmp_path, now=0.0, label="world")
    assert p.parent == tmp_path / "runs" / "screenshots" and p.suffix == ".png" and p.name.startswith("world-")
    assert screenshot.screenshot_path(None, now=0.0).parts[:2] == ("runs", "screenshots")
    assert screenshot.screenshot_path(tmp_path, now=0.0) != screenshot.screenshot_path(tmp_path, now=5.0)


def test_screenshot_save_calls_the_framebuffer(tmp_path):
    class D:
        def output_frame_buffer(self, path):
            self.path = path
    d = D()
    out = screenshot.save(d, tmp_path)
    assert d.path == str(out) and out.parent.is_dir()


def test_gb_tint_uses_only_the_four_greens():
    img = np.random.default_rng(1).integers(0, 256, (20, 20, 3), dtype=np.uint8)
    out = gb_tint(img)
    assert {tuple(int(v) for v in px) for px in out.reshape(-1, 3)} <= set(GB_GREENS)
    assert tuple(gb_tint(np.zeros((1, 1, 3), np.uint8))[0, 0]) == GB_GREENS[0] and tuple(gb_tint(np.full((1, 1, 3), 255, np.uint8))[0, 0]) == GB_GREENS[3]


def test_roster_rows():
    t = Track("agent-2", moved_at=90.0, goal="g")
    s = snap(goals=[Goal("g1", "beat_misty", "current")], screen=Screen(party=[PartyMon("PIKACHU", 17, 30, 45)]))
    r = roster.rows([t], lambda _a: s, lambda _a: STALLED, 100.0)[0]
    assert (r.name, r.stage, r.hp, r.max_hp, r.level, r.idle_s, r.state) == ("agent-2", "beat_misty", 30, 45, 17, 10.0, STALLED)
    assert r.colour == agent_colour("agent-2") and abs(r.hp_frac - 2 / 3) < 1e-9
    assert r.text() == "agent-2  beat_misty  HP 30/45  L17  idle 10s"
    bare = roster.rows([t], lambda _a: None, lambda _a: OK, 100.0)[0]
    assert bare.stage == "g" and bare.max_hp == 0 and "HP" not in bare.text()
    assert roster.fmt_idle(30) == "30s" and roster.fmt_idle(600) == "10m" and roster.fmt_idle(7300) == "2h"


def test_window_scale_and_theme_modes():
    assert window_scale(1280, 800) == 1.0
    assert window_scale(3840, 2160) == 1.6 and window_scale(400, 300) == 0.85
    assert window_scale(1920, 1080) > 1.0 and window_scale(0, 0) == 1.0
    assert toggle("dark") == "light" and toggle("light") == "dark"
    assert palette("light")["bg"] != palette("dark")["bg"] and palette("nope") == palette("dark")


def test_draw_agent_label_pill_pixels():
    from pokeagent.atlas.world import Place, WorldLayout
    from pokeagent.world.draw import SpriteBook, render_state
    from test_world_view import synth_rom
    lay = WorldLayout({0: Place(2, 3, 10, 9, False)}, 30, 14, 14)
    base = np.full((lay.size_px[1], lay.size_px[0], 3), 200, dtype=np.uint8)
    t = Track("gen#1", map=0, x=5, y=5, moved_at=-10.0)
    out = render_state(base, lay, [t], SpriteBook(synth_rom()), 1.0, trails=False)
    x, y = lay.to_world(0, 5, 5)
    above = out[y - 30:y - 10, x - 20:x + 40]
    assert (above.sum(axis=2) < 200).any()                                  # the dark pill is there, above the sprite


def test_trail_alpha_stays_in_range_for_short_trails():
    from pokeagent.world.anim import trail_alpha
    for n in range(1, 130):
        for a in range(0, n, 8):
            assert 0 <= trail_alpha(a, n) <= 255
    assert trail_alpha(0, 2) == 255 and trail_alpha(0, 120) < trail_alpha(112, 120)


def test_gb_tint_matches_float_reference_without_float_temporaries():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (40, 40, 3), dtype=np.uint8)
    lum = img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114
    ref = np.asarray(GB_GREENS, dtype=np.uint8)[np.clip((lum / 64.0).astype(np.int32), 0, 3)]
    out = gb_tint(img)
    assert out.dtype == np.uint8 and (out != ref).mean() < 0.01             # integer weights: only boundary pixels may differ


def test_roster_text_colours_follow_the_theme():
    from pokeagent.viewer.theme_colours import DARK, LIGHT, rgba, state_rgb, text_rgba
    assert state_rgb("ok", True, "light")[:3] == rgba(LIGHT["text"])[:3] != state_rgb("ok", True, "dark")[:3]
    assert state_rgb("ok", True, "dark")[:3] == rgba(DARK["text"])[:3]
    assert text_rgba("light", "dim") == rgba(LIGHT["dim"]) and text_rgba("dark", "dim") == rgba(DARK["dim"])
    assert state_rgb("stalled", False, "light")[:3] == (255, 60, 60)


def test_minimap_texture_uploads_once_per_pyramid(monkeypatch):
    import sys
    import types
    fake = types.SimpleNamespace(calls=0, delete_item=lambda *_a, **_k: None)

    def add_static_texture(*_a, **_k):
        fake.calls += 1
        return fake.calls
    fake.add_static_texture = add_static_texture
    dpg_pkg = types.ModuleType("dearpygui")
    dpg_pkg.dearpygui = fake
    monkeypatch.setitem(sys.modules, "dearpygui", dpg_pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", fake)
    from pokeagent.viewer.ui import world_minimap
    monkeypatch.setattr(world_minimap, "dpg", fake)
    monkeypatch.setattr(world_minimap, "to_gpu", lambda rgb: rgb)

    class Pyr:
        def level(self, _f):
            return np.zeros((4, 4, 3), np.uint8)
    pyr = Pyr()
    m = world_minimap.Minimap(types.SimpleNamespace(pyr=pyr))
    for _ in range(5):
        m._texture()
    assert fake.calls == 1
    m.view.pyr = Pyr()
    m._texture()
    assert fake.calls == 2


def test_world_status_counts_tracked_agents():
    from pokeagent.viewer.ui import world_status
    assert world_status.lines("", True, 0)[0].startswith("waiting")
    assert world_status.lines("", True, 2) == []
