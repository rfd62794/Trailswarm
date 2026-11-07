import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pokeagent.atlas import sprites
from pokeagent.atlas.world import CELL, Place, WorldLayout
from pokeagent.viewer.layout import FocusState
from pokeagent.world import anim, events as ev, stadium
from pokeagent.world.draw import SpriteBook, compose_layers
from pokeagent.world.export import World, export_png
from pokeagent.world.model import BattleCard, Track, WorldModel
from pokeagent.world.pyramid import CHUNK, Pyramid
from pokeagent.world.view import Viewport, locate, pick

ROM = Path("roms/Pokemon Red.gb")


def synth_rom() -> bytes:
    rom = bytearray(0x20000)
    t = sprites.SPRITE_SHEETS
    for i, ptr in enumerate((0x4180, 0x4300, 0x4480)):
        rom[t + 4 * i:t + 4 * i + 4] = bytes([ptr & 255, ptr >> 8, 0xC0, 5])
    off = 5 * 0x4000 - 0x4000 + 0x4180
    for k in range(24 * 16):                       # alternate plane bytes so frames have shades 1..3
        rom[off + k] = 0xFF if k % 2 == 0 else 0x0F
    return bytes(rom)


def layout() -> WorldLayout:
    return WorldLayout({0: Place(2, 3, 10, 9, False), 1: Place(20, 3, 6, 6, False)}, 30, 14, 14)


def test_sprite_bit_order_and_planes():
    tile = bytes([0b10000000, 0b00000000] + [0, 0] * 7)                 # leftmost pixel, low plane only -> shade 1
    t = sprites.decode_tiles(tile, 1)
    assert t[0, 0, 0] == 1 and t[0, 0, 1] == 0
    tile = bytes([0b00000001, 0b00000001] + [0, 0] * 7)                 # rightmost pixel, both planes -> shade 3
    assert sprites.decode_tiles(tile, 1)[0, 0, 7] == 3


def test_decode_frames_tile_layout():
    px = bytes([0x80, 0x00] + [0, 0] * 7)                               # one marked pixel at tile top-left
    raw = px + bytes(16) + bytes(16) + bytes(16)                        # 4 tiles: marker in the top-left tile only
    fr = sprites.decode_frames(raw, 4)
    assert fr.shape == (1, 16, 16) and fr[0, 0, 0] == 1 and fr.sum() == 1
    raw = bytes(16) * 3 + px                                            # marker in the bottom-right tile
    assert sprites.decode_frames(raw, 4)[0, 8, 8] == 1


def test_sheet_frames_and_facing():
    rom = synth_rom()
    sh = sprites.sheet(rom, 1)
    assert sh.shape == (6, 16, 16)                                      # walks: next pointer is 0x180 later
    left, right = sprites.pick_frame(sh, "LEFT"), sprites.pick_frame(sh, "RIGHT")
    assert np.array_equal(left[:, ::-1], right)
    rgba = sprites.sprite_rgba(sprites.pick_frame(sh, "DOWN"), (255, 0, 0))
    assert rgba.shape == (18, 18, 4)
    with pytest.raises(ValueError):
        sprites.sheet(rom, 0)


def test_world_coordinate_placement():
    lay = layout()
    t = Track("a", map=1, x=2, y=4)
    assert anim.place(t, lay, 0.0)[:2] == ((20 + 2) * CELL, (3 + 4) * CELL)
    assert locate(lay, (20 + 2) * CELL + 3, (3 + 4) * CELL + 5) == (1, 2, 4)
    assert locate(lay, 0, 0) is None
    assert anim.place(Track("b", map=77), lay, 0.0) is None


def test_smooth_interpolation_between_moves():
    lay = layout()
    t = Track("a", map=0, x=5, y=5, prev=(0, 4, 5), moved_at=10.0)
    x0 = (2 + 4) * CELL
    assert anim.place(t, lay, 10.0)[0] == x0
    mid = anim.place(t, lay, 10.0 + anim.STEP_S / 2)
    assert x0 < mid[0] < x0 + CELL and mid[2] in (1, 2)
    end = anim.place(t, lay, 11.0)
    assert end[0] == x0 + CELL and end[2] == 0
    t.prev = (1, 0, 0)                                                   # came from another map: no sliding
    assert anim.place(t, lay, 10.01)[0] == x0 + CELL


def test_focus_return_mode_transitions():
    f = FocusState()
    assert f.view == "grid"
    f.toggle_mode()
    assert f.view == "world"
    f.focus("a")
    assert f.view == "focus"
    f.toggle_mode()                                                      # ignored while focused
    assert f.mode == "world"
    f.back()
    assert f.view == "world" and f.focused is None
    f.set_mode("grid")
    f.focus("a")
    f.toggle("a")
    assert f.view == "grid"
    f.back()
    f.toggle_mode()
    assert f.view == "world"                                             # a stray back() does not revert the mode


def test_aggregator_union_and_attribution():
    wm = WorldModel(clock=lambda: 5.0)
    a, b = ev.EventBus(), ev.EventBus()
    a.emit(ev.Move(map=0, x=1, y=1))
    a.emit(ev.Learn(kind="wall", map=0, x=1, y=1, dir="UP"))
    a.emit(ev.Learn(kind="warp", map=0, x=3, y=3, dir="DOWN", dest=[7, 1, 2]))
    b.emit(ev.Move(map=0, x=9, y=9))
    b.emit(ev.Learn(kind="wall", map=0, x=1, y=1, dir="UP"))
    b.emit(ev.Learn(kind="wall", map=0, x=2, y=2, dir="LEFT"))
    wm.ingest("a", a.since(0))
    wm.ingest("b", b.since(0))
    wm.ingest("b", b.since(0))                                           # replays are ignored (seq cursor)
    by = {(v.kind, v.x, v.y): v for v in wm.learned()}
    assert len(by) == 3 and by[("wall", 1, 1)].agent == "a" and by[("wall", 1, 1)].also == ("b",)
    m = wm.union_model()["maps"]["0"]
    assert sorted(m["blocked"]) == ["1,1,UP", "2,2,LEFT"] and m["warps"] == {"3,3,DOWN": [7, 1, 2]}
    assert m["visited"] == {"1,1": 1, "9,9": 1}
    assert [t.id for t in wm.tracks()] == ["a", "b"]
    assert wm.feed({"learn"}, 10)[0][0] == "a"


def test_poll_reads_sources_concurrently_and_survives_failures():
    class Src:
        def __init__(self, i, boom=False):
            self.agent_id, self.bus, self.boom = i, ev.EventBus(), boom
            self.bus.emit(ev.Move(map=0, x=1, y=2))

        def events(self, since):
            if self.boom:
                raise RuntimeError("down")
            return self.bus.payload(since)

    class NoEvents:
        agent_id = "n"

    wm = WorldModel()
    wm.poll([Src("ok"), Src("bad", True), NoEvents()])
    deadline = time.time() + 3
    while [t.id for t in wm.tracks()] != ["ok"] and time.time() < deadline:
        time.sleep(0.01)
    assert [t.id for t in wm.tracks()] == ["ok"]


def test_poll_does_not_wait_for_a_hung_agent():
    release = threading.Event()

    class Hung:
        agent_id = "hung"

        def events(self, since):
            release.wait(5)
            return {"events": []}

    class Fast:
        agent_id = "fast"

        def events(self, since):
            b = ev.EventBus()
            b.emit(ev.Move(map=0, x=1, y=1))
            return b.payload(since)

    wm = WorldModel()
    t0 = time.time()
    wm.poll([Hung(), Fast()])
    assert time.time() - t0 < 1.0                                       # no barrier on the slowest agent
    wm.poll([Hung(), Fast()])                                           # the hung one is not resubmitted while in flight
    release.set()


def test_restart_with_same_id_resets_track_and_replays():
    wm = WorldModel()
    old = ev.EventBus()
    old.emit(ev.Move(map=0, x=1, y=1))
    old.emit(ev.BattleStart(species="X"))
    old.emit(ev.Learn(kind="wall", map=0, x=1, y=1, dir="UP"))
    for _ in range(5):
        old.emit(ev.Move(map=0, x=2, y=2))
    wm.ingest("a", old.since(0), old.epoch)
    other = ev.EventBus()
    other.emit(ev.Learn(kind="wall", map=0, x=9, y=9, dir="UP"))
    wm.ingest("b", other.since(0), other.epoch)
    assert wm.track("a").battle is not None and wm.track("a").last_seq == 8
    new = ev.EventBus()                                                  # the agent rebooted: seq starts again at 1
    new.emit(ev.Move(map=3, x=7, y=7))
    new.emit(ev.Learn(kind="wall", map=0, x=1, y=1, dir="UP"))           # a replayed fact
    wm.ingest("a", new.payload(8)["events"], new.epoch)
    t = wm.track("a")
    assert (t.map, t.x, t.y) == (3, 7, 7) and t.battle is None and list(t.path) == [(3, 7, 7)] and t.prev is None
    assert t.last_seq == 2
    by = {(v.kind, v.x): v for v in wm.learned()}
    assert by[("wall", 1)].agent == "a" and by[("wall", 1)].also == ()    # not re-credited, no phantom co-learner
    assert by[("wall", 9)].agent == "b"


def test_restart_detected_through_poll_with_stale_cursor():
    old, new = ev.EventBus(), ev.EventBus()
    for _ in range(5):
        old.emit(ev.Move(map=0, x=1, y=1))
    for i in range(7):
        new.emit(ev.Move(map=1, x=i, y=0))                              # the new boot is already past the old cursor

    class Src:
        agent_id = "a"
        bus = old

        def events(self, since):
            return self.bus.payload(since)
    src = Src()
    wm = WorldModel(clock=lambda: 0.0)
    wm._read_one(src)
    assert wm.track("a").last_seq == 5
    src.bus = new
    wm._read_one(src)
    t = wm.track("a")
    assert t.last_seq == 7 and t.map == 1 and len(t.path) == 7          # re-polled from 0: nothing lost


def test_plan_caps_chunks_and_coarser_fallback_maps_exactly():
    base = np.zeros((11488 // 4, 5632 // 4, 3), dtype=np.uint8)
    p = Pyramid(base)
    f, cs = p.plan(1.0, (0, 0, 1408, 2872), max_chunks=4)
    assert len(cs) <= 4 and f > 1                                        # zoomed out over a lot of map: a coarser level
    pcx, pcy, u0, v0, u1, v1 = p.parent(1, 1, 1, 2)
    assert (pcx, pcy) == (0, 0) and u0 == pytest.approx(512 / 704) and v0 == 0.5 and u1 == pytest.approx(1.0) and v1 == pytest.approx(1.0)


def test_battle_lifecycle_and_stadium_cap():
    clock = [0.0]
    wm = WorldModel(clock=lambda: clock[0])
    buses = []
    for i in range(11):
        bus = ev.EventBus()
        buses.append(bus)
        bus.emit(ev.BattleStart(species="RATTATA", enemy_level=3, hp=10, max_hp=10, enemy_hp=8, enemy_max_hp=8))
        bus.emit(ev.BattleTurn(turn=1, hp=7, max_hp=10, enemy_hp=2, enemy_max_hp=8, move="EMBER", effect="x2"))
        wm.ingest(f"ag{i:02d}", bus.since(0))
    shown, over = stadium.strip(wm.stadium())
    assert len(shown) == 8 and over == 3                                 # never more than 8 cards
    buses[0].emit(ev.BattleEnd(result="won", turns=1))
    wm.ingest("ag00", buses[0].since(2))
    assert stadium.strip(wm.stadium())[0][0][0] != "ag00"                # finished battles sort after open ones
    assert "RESULT: won" in stadium.lines(wm.track("ag00").battle)
    clock[0] = 10.0
    assert "ag00" not in [a for a, _ in wm.stadium()]                    # closes a few seconds after battle_end


def test_viewport_zoom_pan_pick():
    vp = Viewport(1000, 2000, 400, 400)
    vp.fit()
    assert vp.zoom == 0.125  # Fit snaps to a crisp level (exact fit 0.2)
    before = vp.to_world(100, 120)
    vp.zoom_at(100, 120, 2.0)
    assert vp.to_world(100, 120) == pytest.approx(before)
    c = (vp.cx, vp.cy)
    vp.pan(10, 0)
    assert vp.cx < c[0]
    sx, sy = vp.to_screen(500, 900)
    assert pick({"a": (500, 900), "b": (0, 0)}, vp, sx + 3, sy) == "a" and pick({"b": (0, 0)}, vp, sx, sy) is None


def test_pyramid_levels_and_chunks_stay_small():
    base = np.zeros((2500, 3000, 3), dtype=np.uint8)
    p = Pyramid(base)
    assert p.level_for_zoom(1.0) == 1 and p.level_for_zoom(0.3) == 2 and p.level_for_zoom(0.1) == 8
    assert p.level(4).shape[:2] == (625, 750)
    ch = p.chunks(1, 0, 0, 3000, 2500)
    assert len(ch) == 9 and all(max(p.chunk(1, *c).shape[:2]) <= CHUNK for c in ch)
    assert p.chunks(1, 1100, 100, 1200, 200) == [(1, 0)]
    assert p.chunk_rect(1, 2, 2) == (2048, 2048, 3000, 2500)


def test_png_export_of_a_fake_world(tmp_path):
    lay, rom = layout(), synth_rom()
    base = np.full((lay.size_px[1], lay.size_px[0], 3), 200, dtype=np.uint8)
    w = World(rom, {}, lay, base, SpriteBook(rom))
    t = Track("agent-1", map=0, x=4, y=4, facing="LEFT")
    t.path.extend([(0, 2, 4), (0, 3, 4), (0, 4, 4)])
    t2 = Track("agent-2", map=1, x=1, y=1, battle=BattleCard(species="PIDGEY"))
    out = tmp_path / "w.png"
    assert export_png(out, w, [t, t2], now=1.0) == lay.size_px
    img = np.asarray(Image.open(out))
    x, y = lay.to_world(0, 4, 4)
    assert (img[y:y + 16, x:x + 16] != 200).any()                        # the sprite was drawn on its cell
    assert (img[0:CELL, 0:CELL] == 200).all()
    crop = tmp_path / "c.png"
    assert export_png(crop, w, [t], crop=(0, 0, 160, 160), scale=0.5, now=1.0) == (80, 80)


def test_compose_layers_draws_beliefs():
    lay = layout()
    base = np.zeros((lay.size_px[1], lay.size_px[0], 3), dtype=np.uint8)
    out = compose_layers(base, lay, {"maps": {"0": {"blocked": ["1,1,UP"]}}}, {}, ("walls",))
    assert (out != base).any() and out is not base


@pytest.mark.skipif(not ROM.exists(), reason="needs the ROM")
def test_rom_player_sprite_and_npc_sheets():
    rom = ROM.read_bytes()
    red = sprites.sheet(rom, 1)
    assert red.shape == (6, 16, 16) and (red > 0).sum() > 100
    assert all(len(sprites.sheet(rom, i)) in (1, 3, 6) for i in range(1, 40))


def test_dpg_world_mode_headless():
    dpg = pytest.importorskip("dearpygui.dearpygui")
    from pokeagent.viewer.model import ViewerModel
    from pokeagent.viewer.ui.window import ViewerWindow
    lay, rom = layout(), synth_rom()
    world = World(rom, {}, lay, np.full((lay.size_px[1], lay.size_px[0], 3), 90, dtype=np.uint8), SpriteBook(rom))
    wm = WorldModel()
    bus = ev.EventBus()
    bus.emit(ev.Move(map=0, x=3, y=3, facing="UP"))
    bus.emit(ev.BattleStart(species="PIDGEY", enemy_level=4, hp=10, max_hp=10, enemy_hp=5, enemy_max_hp=5))
    wm.ingest("a0", bus.since(0))
    win = ViewerWindow(ViewerModel(), {}, world=wm)
    wv = lambda: win.world.view
    try:
        win._build()
        dpg.setup_dearpygui()
        win._populate()
    except Exception as e:
        pytest.skip(f"Dear PyGui cannot build widgets without a viewport: {e}")
    try:
        wv()._load(lambda: world)
        wv()._started = True
        win.focus.toggle_mode()
        assert win.focus.view == "world"
        for _ in range(3):
            win.tick()
        assert "a0" in wv()._points
        win.toggle_focus("a0")
        assert win.focus.view == "focus"
        win.leave_focus()
        assert win.focus.view == "world"
    finally:
        dpg.destroy_context()


def test_cli_world_help(capsys):
    from pokeagent.cli import main
    with pytest.raises(SystemExit) as ei:
        main(["world", "--help"])
    assert ei.value.code == 0
    assert "--png" in capsys.readouterr().out
