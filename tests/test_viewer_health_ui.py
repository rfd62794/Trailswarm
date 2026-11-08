"""Health UI under ``dpg.create_context()`` (no viewport): header tint memoise, badge text,
anomaly click-through, and the 1 Hz poll wiring."""

import importlib


from pokeagent.viewer import health as hm


def _ctx(dpg):
    dpg.create_context()
    if not dpg.does_item_exist("viewer_tex"):
        dpg.add_texture_registry(tag="viewer_tex", show=False)


def _destroy(dpg):
    try:
        dpg.destroy_context()
    except Exception:
        pass


def test_badge_text_formats():
    ok = {"errors": 0, "warns": 0, "top": []}
    assert hm.badge_text({hm.STALLED: 0}, ok) == "Health: 0 stalled | invariants: 0 errors"
    assert "1 stalled, 1 anomaly" in hm.badge_text({hm.STALLED: 1, hm.ANOMALY: 1}, ok)
    assert "2 slow" in hm.badge_text({hm.SLOW: 2}, ok)
    assert hm.badge_text({}, {"unavailable": "no rom"}) == "Health: 0 stalled | invariants: unavailable"
    assert hm.badge_text({}, None) == "Health: 0 stalled | invariants: checking..."


def test_poller_health_tick_cadence():
    """The poller wiring refreshes once per fps * HEALTH_POLL_S ticks (a fake tick loop, no thread)."""
    calls = []

    class FakeStore:
        def refresh(self, root, now):
            calls.append("refresh")

        def request_invariants(self, root, now):
            calls.append("inv")

    store = FakeStore()
    for tick in range(1, 3 * 30 + 1):
        if hm.poll_due(tick, 30):
            store.refresh(".", tick)
            store.request_invariants(".", tick)
    assert calls == ["refresh", "inv"] * 3
    assert [t for t in range(1, 91) if hm.poll_due(t, 30)] == [30, 60, 90]


def test_card_header_tint_memoised_by_state(monkeypatch):
    dpg = importlib.import_module("dearpygui.dearpygui")
    from pokeagent.viewer.ui import theme
    from pokeagent.viewer.ui.card import CardView
    _ctx(dpg)
    try:
        with dpg.window():
            parent = dpg.add_group()
            card = CardView(parent, "a", 300, 200, lambda a: None, lambda a: None)
    except BaseException:
        _destroy(dpg)
        raise
    try:
        tints = []
        real = dpg.configure_item
        monkeypatch.setattr(dpg, "configure_item",
                            lambda item, **kw: (tints.append(kw.get("tint_color")), real(item, **kw))[1])
        card.set_health(hm.STALLED, "menu loop")
        card.set_health(hm.STALLED, "menu loop")        # unchanged: no re-theme
        card.set_health(hm.ANOMALY, "endless battle")
        card.set_health(hm.OK, "")
        got = [t for t in tints if t is not None]
        assert got == [theme.HEADER_COLOUR[hm.STALLED], theme.HEADER_COLOUR[hm.ANOMALY],
                       theme.HEADER_COLOUR[hm.OK]]
    finally:
        _destroy(dpg)


def test_anomaly_click_loads_texture_once_and_missing_file(monkeypatch, tmp_path):
    dpg = importlib.import_module("dearpygui.dearpygui")
    from pokeagent.viewer.ui.health_panel import HealthPanel
    _ctx(dpg)
    try:
        with dpg.window():
            parent = dpg.add_group()
            panel = HealthPanel(parent)
    except BaseException:
        _destroy(dpg)
        raise
    try:
        panel.bind(hm.HealthStore(), {})
        png = tmp_path / "explore-20261107-150000-1-42-endless_battle.png"
        png.write_bytes(b"not a real png; dpg.load_image is faked")
        png2 = tmp_path / "explore-20261107-150000-1-43-endless_battle.png"
        png2.write_bytes(b"same")
        loads = []
        monkeypatch.setattr(dpg, "load_image", lambda p: (loads.append(p), (1, 1, 4, [1.0] * 4))[1])
        ref = hm.AnomalyRef(run="explore-20261107-150000-1", step=42, type="endless_battle",
                            png=png, state=tmp_path / "s.state", mtime=0.0, cause_hint="loop")
        panel.show_anomaly(ref)
        assert loads == [str(png)] and panel._tex is not None
        first_tex = panel._tex[1]
        panel.show_anomaly(ref)                          # same path: cached, no reload
        assert loads == [str(png)]
        ref2 = hm.AnomalyRef(run="explore-20261107-150000-1", step=43, type="endless_battle",
                             png=png2, state=None, mtime=0.0)
        panel.show_anomaly(ref2)                         # new image: previous texture deleted
        assert loads == [str(png), str(png2)] and not dpg.does_item_exist(first_tex)
        missing = hm.AnomalyRef(run="explore-20261107-150000-1", step=44, type="endless_battle",
                                png=tmp_path / "nope.png", state=None, mtime=0.0)
        panel.show_anomaly(missing)                      # no raise; the slot says "file missing"
        assert "file missing" in str(dpg.get_value(panel.detail_head))
    finally:
        _destroy(dpg)
