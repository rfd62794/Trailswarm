"""World-view memory: per-agent state is pruned when an agent leaves ``discover()``, shared-memory handles are closed and the
GPU textures the view creates are all deleted. 50 agents arrive and leave in sequence; nothing may stay behind. Headless."""
from __future__ import annotations

import numpy as np

from pokeagent.viewer import app, sources
from pokeagent.viewer.model import ViewerModel
from pokeagent.viewer.ui import world_interiors, world_minimap, world_view
from pokeagent.world import events as ev
from pokeagent.world.model import WorldModel
from pokeagent.world.pyramid import Pyramid
from pokeagent.viewer.dpg_stub import StubDpg

N = 50


class _Src:
    """A registry-backed source: counts closes like HttpShmSource does."""

    def __init__(self, aid: str) -> None:
        self.agent_id, self.closed = aid, 0
        self._bus = ev.EventBus()
        self._n = 0

    def events(self, since: int = 0) -> dict:
        self._n += 1
        self._bus.emit(ev.Move(map=0, x=self._n, y=1, facing="DOWN", step=self._n))
        return self._bus.payload(since)

    def snapshot(self):
        return None

    def frame(self):
        return (bytes(3), 1, 1)

    def close(self) -> None:
        self.closed += 1


def _sizes(model: ViewerModel, wm: WorldModel) -> dict:
    return {"model": (len(model._snap), len(model._frame), len(model._last_ok), len(model._fails), len(model._snap_at),
                      len(model._frame_at), len(model._inflight)),
            "world": (len(wm._tracks), len(wm._since), len(wm._epoch), len(wm._polled), len(wm._inflight), len(wm._feed))}


def test_fifty_agents_come_and_go_and_the_caches_return_to_baseline():
    model, wm = ViewerModel(), WorldModel()
    holder = {"sources": {}, "entries": {}}
    base = _sizes(model, wm)
    made: list[_Src] = []
    for i in range(N):
        src = _Src(f"explore-{1000 + i}")
        made.append(src)
        refresh_fresh = {src.agent_id: src}                    # the registry now lists only this agent: the previous one exited
        app.refresh_sources(holder, model, refresh_fresh, {src.agent_id: {"id": src.agent_id}}, wm)
        srcs = list(holder["sources"].values())
        model.set_wants(None, {src.agent_id: 10.0})
        for _ in range(3):
            model.poll(srcs); wm.poll(srcs)
            model.drain(); wm.drain()
            model._snap_at.clear(); model._frame_at.clear(); wm._polled.clear()   # every loop tick is "due" in this test
        assert set(wm.ids()) == {src.agent_id}                 # only the live agent has a track
    app.refresh_sources(holder, model, {}, {}, wm)             # the last one exits too
    wm.drain()
    app.refresh_sources(holder, model, {}, {}, wm)             # a read in flight at exit may land late: the next scan sweeps it
    assert _sizes(model, wm)["world"] == base["world"]
    assert not model._snap and not model._frame and not model._focused
    assert wm.ids() == [] and not wm._polled and not wm._since
    assert all(s.closed == 1 for s in made), [s.closed for s in made if s.closed != 1]   # every source detached exactly once


def test_rescan_closes_sources_it_does_not_adopt():
    keep, dup = _Src("a"), _Src("a")
    holder = {"sources": {"a": keep}, "entries": {}}
    app.merge_sources(holder["sources"], {"a": dup})
    assert holder["sources"]["a"] is keep and dup.closed == 1 and keep.closed == 0


def test_worldmodel_forget_drops_every_per_agent_key_and_feed_rows():
    wm = WorldModel()
    for aid in ("x", "y"):
        wm.ingest(aid, [ev.Move(seq=1, map=0, x=1, y=1).to_dict(), ev.Move(seq=2, map=0, x=2, y=1).to_dict()], "e1")
        wm._polled[aid] = 1.0
        wm._inflight.add(aid)
    wm.set_focus("x")
    wm.forget("x")
    assert wm.ids() == ["y"] and "x" not in wm._polled and "x" not in wm._inflight and wm._focused is None
    assert {a for a, _ in wm.feed()} == {"y"}
    wm.ingest("x", [ev.Move(seq=1, map=0, x=1, y=1).to_dict()], "e2")      # a late read resurrects it ...
    assert wm.sweep(["y"]) == ["x"] and wm.ids() == ["y"]                  # ... and the next scan sweeps it


def test_trail_history_is_bounded():
    wm = WorldModel()
    wm.ingest("a", [ev.Move(seq=i, map=0, x=i, y=0).to_dict() for i in range(1, 5000)], "e")
    assert len(wm.track("a").path) == 400 and len(wm.feed(limit=10_000)) <= 600


def test_http_source_close_detaches_the_slot_and_never_reattaches():
    class Sub:
        def __init__(self):
            self.attached, self.reads = True, 0
            self.owner_pid = 7

        def read(self):
            self.reads += 1
            self.attached = True
            return (bytes(3), 1, 1)

        def close(self):
            self.attached = False

    src = sources.HttpShmSource({"id": "a", "port": 1, "pid": 7})
    src._sub = Sub()
    assert src.frame() is not None
    src.close()
    src.close()                                                # idempotent
    assert src._sub.attached is False and src.frame() is None and src._sub.reads == 1


# -- the view's textures --------------------------------------------------------------------------------------------
class _Book:
    def image(self, *_a):
        return np.zeros((18, 18, 4), np.uint8)


class _Pyr(Pyramid):
    def __init__(self, tag: int) -> None:
        super().__init__(np.full((64, 64, 3), tag, np.uint8))


def _view(monkeypatch):
    stub = StubDpg()
    for mod in (world_view, world_minimap, world_interiors):
        monkeypatch.setattr(mod, "dpg", stub)
    monkeypatch.setattr(world_interiors.Overrides, "load", classmethod(lambda cls, *a, **k: world_interiors.Overrides.__new__(cls)))
    monkeypatch.setattr(world_interiors.EditLayout, "__init__", lambda self, layer: None)
    monkeypatch.setattr(world_interiors.StretchSwap, "__init__", lambda self, layer: None)
    monkeypatch.setattr(world_interiors.InteriorLayer, "__init__", _fake_interiors_init)
    v = world_view.WorldView(0, WorldModel(), lambda a: None, lambda a: None, lambda: None)
    v.world = type("W", (), {"book": _Book()})()
    return v, stub


def _fake_interiors_init(self, view):
    self.view, self._tex, self._tex_bytes, self._tex_world, self._images, self._used = view, {}, {}, None, None, set()


def test_fifty_agents_and_pyramid_swaps_create_exactly_as_many_textures_as_they_delete(monkeypatch):
    v, dpg = _view(monkeypatch)
    base_live = len(dpg.live)
    for i in range(N):
        aid = f"explore-{2000 + i}"
        v.wm.ingest(aid, [ev.Move(seq=1, map=0, x=1, y=1, facing="LEFT").to_dict()], "e")
        v._points[aid] = (1.0, 1.0)
        v.selected_id = aid
        v.follow.start(aid, 0.0)
        v._adopt_pyramid(_Pyr(i))                              # a layer rebuild: fresh pixels every time
        v.pyr = v.pyr
        for f, cx, cy in ((1, 0, 0), (2, 0, 0), (4, 0, 0)):
            v._uploads = 0
            assert v._chunk_tex(f, cx, cy) is not None
        for t in v.wm.tracks():
            v._agent_tex(t.facing, 0, (230, 25, 75))
        assert len(v._tex) <= 3                                # chunks of dead pyramids are gone at once, not by LRU
        v.wm.forget(aid)                                       # the agent leaves
        v.prune_agents(v.wm.ids())
        assert v.selected_id is None and not v.follow.active and not v._points
    assert len(v._sprite_tex) == 1                             # one colour x facing x phase, not one per agent
    v.mini.view = v
    v.delete()
    assert dpg.created > 3 * N and dpg.created == dpg.deleted + len(dpg.live)
    assert len(dpg.live) == base_live == 0 and not v._tex and not v._sprite_tex


def test_world_swap_drops_sprite_and_chunk_textures(monkeypatch):
    v, dpg = _view(monkeypatch)
    v._adopt_pyramid(_Pyr(1))
    v._chunk_tex(1, 0, 0)
    v._agent_tex("UP", 0, (1, 2, 3))
    assert len(dpg.live) == 2
    v._adopt_pyramid(_Pyr(2)); v._drop_sprites()
    assert not dpg.live and dpg.created == dpg.deleted == 2


def test_interior_textures_are_trimmed_to_a_byte_budget_and_freed_on_world_swap(monkeypatch):
    v, dpg = _view(monkeypatch)
    lay = v.interiors
    lay.view = v
    w1, w2 = object(), object()
    monkeypatch.setattr(world_interiors, "MAX_TEX_BYTES", 4 * 100 * 100 * 16)
    for k in range(10):                                        # ten 100x100 rooms, frame by frame
        lay._purge(w1)
        key = (id(w1), k, 1.0, 1)
        lay._tex[key] = dpg.add_static_texture(100, 100, None)
        lay._tex_bytes[key] = 100 * 100 * 16
        lay._used.add(key)
    lay._purge(w1)                                             # over budget: everything not drawn last frame goes
    lay._purge(w1)
    assert sum(lay._tex_bytes.values()) <= 4 * 100 * 100 * 16 and set(lay._tex) == set(lay._tex_bytes)
    lay._purge(w2)                                             # new world: all of it goes
    assert not lay._tex and not lay._tex_bytes and not dpg.live and dpg.created == dpg.deleted == 10
