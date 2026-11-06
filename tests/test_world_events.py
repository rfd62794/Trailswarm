import json
import time
import urllib.request

from pokeagent.adapters.event_feed import EventFeed
from pokeagent.control_server import ControlServer
from pokeagent.snapshot import AgentSnapshot
from pokeagent.world import events as ev


def test_ring_is_bounded_and_seq_monotonic():
    bus = ev.EventBus(capacity=5)
    for i in range(12):
        bus.emit(ev.Move(x=i))
    got = bus.since(0)
    assert [e["seq"] for e in got] == [8, 9, 10, 11, 12]          # oldest dropped, seq never reused
    assert [e["x"] for e in got] == [7, 8, 9, 10, 11]


def test_since_cursor_and_limit():
    bus = ev.EventBus()
    for i in range(10):
        bus.emit(ev.Move(x=i))
    assert [e["seq"] for e in bus.since(7)] == [8, 9, 10]
    assert bus.since(10) == []
    assert len(bus.since(0, limit=4)) == 4 and bus.since(0, limit=4)[0]["seq"] == 1


def test_roundtrip_and_unknown_types():
    bus = ev.EventBus()
    bus.emit(ev.Learn(kind="warp", map=3, x=1, y=2, dir="UP", dest=[4, 5, 6]))
    d = bus.since(0)[0]
    assert d["type"] == "learn" and d["v"] == ev.EVENT_SCHEMA
    back = ev.from_dict(json.loads(json.dumps(d)))
    assert isinstance(back, ev.Learn) and back.dest == [4, 5, 6] and back.seq == 1
    assert ev.from_dict({"type": "nope"}) is None and ev.from_dict("x") is None
    assert ev.from_dict({"type": "move", "v": 99}) is None
    assert ev.from_dict({"type": "move", "extra": 1, "x": 3}).x == 3          # unknown keys ignored


def test_every_type_serialises():
    for name, cls in ev.TYPES.items():
        assert ev.from_dict(cls().to_dict()).TYPE == name


def test_events_endpoint_is_token_guarded():
    bus = ev.EventBus()
    bus.emit(ev.Move(x=1))
    bus.emit(ev.Move(x=2))
    srv = ControlServer(lambda: AgentSnapshot(agent_id="a"), {}, token="tok", events_fn=bus.since)
    port = srv.start()
    try:
        def get(path, token="tok"):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"X-PokeAgent-Token": token})
            try:
                with urllib.request.urlopen(req, timeout=2) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        code, body = get("/events?since=1")
        assert code == 200 and [e["x"] for e in body] == [2]
        assert get("/events", token="bad")[0] == 403
        assert get("/events?since=zzz")[0] == 400
    finally:
        srv.stop()


class FakeEmu:
    def __init__(self):
        self.mem = {}

    def read(self, a):
        return self.mem.get(a, 0)


def test_feed_emits_moves_map_changes_battles():
    emu, feed = FakeEmu(), EventFeed()
    ctx = type("C", (), {"step": 1})()
    emu.mem.update({0xD35E: 0, 0xD362: 5, 0xD361: 6})
    feed.observe(emu, ctx)
    emu.mem[0xD361] = 5
    feed.observe(emu, ctx)
    emu.mem.update({0xD35E: 1, 0xD362: 2, 0xD361: 2})
    feed.observe(emu, ctx)
    emu.mem.update({0xD057: 1, 0xCFE6: 0, 0xCFE7: 20, 0xCFF4: 0, 0xCFF5: 20, 0xD015: 0, 0xD016: 15, 0xD023: 0, 0xD024: 15})
    feed.observe(emu, ctx)
    emu.mem[0xCFE7] = 0
    feed.observe(emu, ctx)
    emu.mem[0xD057] = 0
    feed.observe(emu, ctx)
    kinds = [e["type"] for e in feed.bus.since(0)]
    assert kinds == ["move", "move", "map_change", "move", "battle_start", "battle_turn", "battle_end"]
    moves = [e for e in feed.bus.since(0) if e["type"] == "move"]
    assert moves[1]["facing"] == "UP"
    assert feed.bus.since(0)[-1]["result"] == "won"


def test_feed_learns_from_memory_delta():
    feed = EventFeed()
    mem = type("M", (), {"data": {"maps": {"3": {"blocked": ["1,2,UP"], "warps": {"4,5,DOWN": [7, 1, 1]}}}}})()
    feed.observe(FakeEmu(), type("C", (), {"step": 0})(), mem)
    mem.data["maps"]["3"]["blocked"].append("2,2,LEFT")
    feed.observe(FakeEmu(), type("C", (), {"step": 0})(), mem)
    learns = [e for e in feed.bus.since(0) if e["type"] == "learn"]
    assert [(e["kind"], e["x"], e["dir"]) for e in learns] == [("wall", 1, "UP"), ("warp", 4, "DOWN"), ("wall", 2, "LEFT")]
    assert learns[1]["dest"] == [7, 1, 1]
