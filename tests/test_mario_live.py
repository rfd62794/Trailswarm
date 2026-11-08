"""The Mario side of the live contract: record building, throttled writes, sprite box."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import mario_live as M  # noqa: E402


class FakeW:
    world = (1, 1)
    level_progress = 42


class FakeMemory:
    def __getitem__(self, addr):
        assert addr == 0xC201
        return 40


class FakePy:
    memory = FakeMemory()


class FakeDisplay:
    agent = "mario-land"
    w = FakeW()
    py = FakePy()
    best = {"at": 1000.000123, "worker": 2}


def test_build_record_schema_one():
    r = M.build_record(FakeDisplay())
    assert r["schema"] == 1 and r["agent"] == "mario-land"
    assert r["area"] == "1-1" and r["x"] == 42 and r["y"] == 8            # same point maths as ghosts
    assert r["screen_x"] is None and r["screen_y"] is None                # tile ids not known yet
    assert r["run"] == f"{int(1000.000123 * 1000)}-2"                     # ghost-run id convention
    assert isinstance(r["updated_at"], float)


def test_build_record_none_for_broken_display():
    class Broken:
        best = None
    assert M.build_record(Broken()) is None


def test_live_writer_throttles(tmp_path):
    calls = []
    w = M.LiveWriter(tmp_path, "mario-land", hz=10.0)
    orig = M.write_live
    try:
        M.write_live = lambda src, rec: calls.append(rec)
        t = 0.0
        for _ in range(200):                                            # 100 Hz calls for 2 s
            w.maybe_write({"schema": 1, "agent": "x", "run": "", "area": "a",
                           "x": 1, "y": 1, "screen_x": None, "screen_y": None,
                           "updated_at": t}, t)
            t += 0.01
    finally:
        M.write_live = orig
    assert 18 <= len(calls) <= 22                                       # ~10 Hz, never more
    assert calls[0]["agent"] == "mario-land"                            # writer's agent is stamped
    n = len(calls)
    w.maybe_write(None, t)                                              # a None state writes nothing
    assert len(calls) == n


def test_live_writer_writes_the_real_file(tmp_path):
    w = M.LiveWriter(tmp_path, "mario-land")
    w.maybe_write(M.build_record(FakeDisplay()), 0.0)
    doc = json.loads((tmp_path / "live" / "mario-land.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and doc["area"] == "1-1"


def test_locate_player_bounding_box():
    sprites = [(10, 20, 5), (18, 24, 7), (0, 0, 9), (12, 22, 5)]
    assert M.locate_player(sprites, {5, 7}) == (10, 20)
    assert M.locate_player(sprites, {99}) is None
    assert M.locate_player([], {5}) is None
    assert M.PLAYER_TILE_IDS == frozenset()                             # empty until the real-window check
