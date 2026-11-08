"""Review fixes on the view presets / avatars work: crop quality, gap default, fast live feed, flicker, edges."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from pokeagent.mapview.areas import Area
from pokeagent.mapview.avatars import AvatarCache, AvatarSource, crop_avatar
from pokeagent.mapview.edges import draw_edges
from pokeagent.mapview.fast_live import live_once
from pokeagent.mapview.holder import Holder
from pokeagent.mapview.layout import DEFAULT_GAP, gap_for, place
from pokeagent.mapview.live import LiveStore, write_live
from pokeagent.mapview.live_schema import safe_name
from pokeagent.mapview.presets import resolve
from pokeagent.mapview.smooth import Smoother
from pokeagent.mapview.walk import LiveTracker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def frame_with_sprite(w=64, h=64, at=(20, 20), size=16, fill=0.5):
    f = np.full((h, w, 3), 100, np.uint8)
    n = int(size * fill)
    f[at[1] + 2:at[1] + 2 + n // 2, at[0] + 2:at[0] + 2 + 8] = (200, 30, 30)
    return f


def live(sx, sy, w=None, h=None):
    return SimpleNamespace(screen_x=sx, screen_y=sy, screen_w=w, screen_h=h)


# 1. throttle first
def test_watch_builds_nothing_when_write_not_due():
    import mario_display as D
    import mario_live as M

    built = []
    w = M.LiveWriter(Path("."), "a", hz=10.0)
    w._last = 1e12                                             # nothing is due
    fake = SimpleNamespace(py=SimpleNamespace(tick=lambda *a: None), pub=SimpleNamespace(publish=lambda **k: None),
                           _live=w, _build_record=lambda d: built.append(1) or {})
    D.Display.watch(fake, 5)
    assert built == []
    assert not w.due(0.0) and M.LiveWriter(Path("."), "a").due(0.0)


# 2. crops
def test_clipped_crop_is_rejected():
    f = frame_with_sprite()
    assert crop_avatar(f, -2, 20, 16) is None
    assert crop_avatar(f, 56, 20, 16) is None
    assert crop_avatar(f, 20, 20, 16) is not None


def test_scenery_touching_the_ring_is_rejected():
    f = frame_with_sprite()
    f[20:36, 20] = (10, 200, 10)                                # a wall along the box's left edge
    assert crop_avatar(f, 20, 20, 16) is None


def test_bbox_overrides_ring_check_and_sizes_the_crop():
    f = frame_with_sprite()
    f[20:36, 20] = (10, 200, 10)
    out = crop_avatar(f, 22, 22, 16, box_wh=(8, 8))
    assert out is not None and out.shape[:2] == (8, 8)


def test_cache_prefers_typical_ratio_over_max_and_mirrors_for_the_other_side():
    cache, preset = AvatarCache(), SimpleNamespace(name="p", avatar_size=16)
    frame = frame_with_sprite(fill=0.9)
    big = np.full((64, 64, 3), 100, np.uint8)
    big[24:38, 24:38] = (30, 200, 30)                           # nearly the whole box: scenery-like
    cache.offer(preset, "RIGHT", frame, live(20, 20))
    held = cache._crops[("p", "RIGHT")]
    cache.offer(preset, "RIGHT", big, live(22, 22))
    assert cache._crops[("p", "RIGHT")] is held                 # the bigger-but-less-typical crop lost
    assert cache.get(preset, "LEFT", (1, 2, 3)) is not None     # LEFT served mirrored from RIGHT
    assert cache.get(preset, "UP", (1, 2, 3)) is None
    assert AvatarSource(cache, preset).ready()


# 3. gap
def test_gap_default_stays_32_unless_preset_asks():
    assert gap_for(resolve(preset="rpg-overworld")) == DEFAULT_GAP == 32
    assert gap_for(resolve(game="pokemon-red")) == 32
    assert gap_for(resolve(preset="flip-screen")) == 32
    assert gap_for(resolve(preset="platformer")) == 8 == gap_for(resolve(game="super-mario-land"))
    a = [Area("a", 10, 10, 1.0, Path("a")), Area("b", 10, 10, 1.0, Path("b"))]
    assert place(a, gap=gap_for(resolve(preset="rpg-overworld"))).offsets["b"][0] == 42


# 4. fast live feed
def _snap(live_pos=None):
    from pokeagent.mapview import playback
    from pokeagent.mapview.holder import Snapshot
    from pokeagent.mapview.layout import Layout
    return Snapshot(Path("."), True, (), {}, Layout({}, 0, 0), playback.tables((), (), 60), live_pos or {})


def test_fast_live_updates_holder_and_survives_slow_set(tmp_path):
    import time
    holder = Holder(_snap())
    store = LiveStore()
    write_live(tmp_path, {"schema": 1, "agent": "a", "run": "", "area": "1", "x": 3.0, "y": 4.0,
                          "screen_x": None, "screen_y": None, "updated_at": time.time()})
    assert live_once(tmp_path, store, holder, None, None, resolve(), None, time.time())
    assert holder.get().live["a"].x == 3.0
    holder.set(_snap({}))                                       # a slow poll with older (empty) live
    assert "a" in holder.get().live


def test_smoother_glides_and_snaps_far_jumps():
    s = Smoother()
    assert s.step({"a": (0.0, 0.0)}, 0.016)["a"] == (0.0, 0.0)
    mid = s.step({"a": (10.0, 0.0)}, 0.016)["a"][0]
    assert 0.0 < mid < 10.0
    assert s.step({"a": (1000.0, 0.0)}, 0.016)["a"] == (1000.0, 0.0)
    assert s.step({}, 0.016) == {}


def test_walk_phase_holds_between_ten_hz_reads():
    t = LiveTracker(True, hold=8)
    t.update("a", "x", 0.0, 0.0)
    _f, p1 = t.update("a", "x", 1.0, 0.0)
    _f, p2 = t.update("a", "x", 1.0, 0.0)
    assert p1 != 0 and p2 == p1
    for _ in range(10):
        _f, p = t.update("a", "x", 1.0, 0.0)
    assert p == 0
    assert LiveTracker(True).update("a", "x", 0, 0)[1] == 0


# 5. overlay cost with no crop
def test_ghost_avatars_not_asked_when_nothing_is_ready():
    from pokeagent.mapview.ghost_avatars import ghost_groups
    calls = []
    av = SimpleNamespace(ready=lambda: False, get=lambda *a: calls.append(a))
    assert ghost_groups(av, None, None, np.array([0, 1]), None, None, None, 10, 10, False) == []
    assert calls == []


# 6. flicker + filename
def test_transient_read_failure_keeps_last_good_record(tmp_path):
    import time
    rec = {"schema": 1, "agent": "a", "run": "", "area": "1", "x": 1.0, "y": 2.0,
           "screen_x": None, "screen_y": None, "updated_at": time.time()}
    write_live(tmp_path, rec)
    store = LiveStore()
    store.refresh(tmp_path, time.time())
    (tmp_path / "live" / "a.json").write_text("{not json", encoding="utf-8")
    store.refresh(tmp_path, time.time())
    assert "a" in store.positions()
    store.refresh(tmp_path, time.time() + 60)                   # but it still goes stale
    assert store.positions() == {}


def test_agent_name_is_sanitised_in_the_filename(tmp_path):
    assert "/" not in safe_name("../../evil/x") and not safe_name("../x").startswith(".")
    assert safe_name("") == "agent"
    import time
    write_live(tmp_path, {"schema": 1, "agent": "../../evil", "run": "", "area": "1", "x": 1.0, "y": 2.0,
                          "screen_x": None, "screen_y": None, "updated_at": time.time()})
    assert [p.parent.name for p in tmp_path.rglob("*.json")] == ["live"]


# 7. edges at the origin
def test_area_at_origin_keeps_left_and_top_edges():
    base = np.zeros((40, 40, 4), np.uint8)
    draw_edges(base, [("a", 0, 0, 20, 20)], {"a": "#ff0000"}, width=2)
    assert (base[5, 0, :3] == (255, 0, 0)).all() and (base[0, 5, :3] == (255, 0, 0)).all()
    assert (base[5, 21, :3] == (255, 0, 0)).all()
