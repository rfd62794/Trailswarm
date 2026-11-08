"""The per-step progress signal: each reason on a crafted Snapshot pair, the counter, the log rows."""
from __future__ import annotations

import json

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.progress import PROGRESS_LOG_EVERY, ProgressLog, ProgressTracker, progress_reasons
from pokeagent.explorer.selector import Selector
from pokeagent.novelty import features as ft

MAP, PX, PY = 0xD35E, 0xD362, 0xD361


def snap(map=1, x=5, y=5, flags=b"", bag=(), money=0, party=(), in_battle=False, hp=0):
    return ft.Snapshot(map, x, y, flags.ljust(ft.FLAGS_LEN, b"\0"), tuple(bag), (), money, tuple(party), in_battle, 0, hp)


def mon(species=177, level=5, exp=100):
    return (species, level, exp, (33,), (1, 2))


def reasons(prev, cur, new_tile=False, gb=0, ga=0, battle_ended=False):
    return progress_reasons(prev, cur, new_tile, gb, ga, battle_ended)


def test_each_reason_fires_on_a_crafted_pair():
    assert "tile" in reasons(snap(), snap(), new_tile=True)
    assert "map" in reasons(snap(), snap(map=2))
    assert "flag" in reasons(snap(), snap(flags=bytes([0b100])))
    assert "xp" in reasons(snap(party=[mon()]), snap(party=[mon(exp=200)]))
    lvl = reasons(snap(party=[mon()]), snap(party=[mon(level=6, exp=200)]))
    assert "xp" in lvl and "level" in lvl
    assert "goal" in reasons(snap(), snap(), ga=1)
    assert "money" in reasons(snap(money=100), snap(money=900))
    assert "item" in reasons(snap(bag=[(20, 3)]), snap(bag=[(20, 2)]))            # a potion used
    assert "item" in reasons(snap(bag=[(20, 3)]), snap(bag=[(20, 3), (4, 1)]))   # a ball picked up
    assert "battle" in reasons(snap(in_battle=True), snap(), battle_ended=True)
    assert "hp" in reasons(snap(hp=10), snap(hp=20))                             # the nurse healed us


def test_a_plain_blocked_press_yields_nothing():
    assert reasons(snap(), snap()) == []
    assert reasons(None, snap()) == []                 # no baseline: nothing provable
    assert reasons(None, snap(), new_tile=True) == ["tile"]


def test_steps_since_increments_and_resets():
    t = ProgressTracker()
    assert t.observe(1, None, snap(), False, 0, 0, False) == [] and t.steps_since == 1
    t.observe(2, snap(), snap(), False, 0, 0, False)
    assert t.steps_since == 2
    assert t.observe(3, snap(), snap(), True, 0, 0, False) == ["tile"] and t.steps_since == 0


def test_progress_log_events_and_heartbeat(tmp_path):
    log = ProgressLog(tmp_path / "progress.jsonl")
    log.event(9, 100, ["tile"], 7)
    log.heartbeat(100, 34)
    log.close()
    rows = [json.loads(ln) for ln in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert rows == [{"step": 9, "frame": 100, "reasons": ["tile"], "since": 7},
                    {"step": 100, "reasons": [], "since": 34}]


def test_a_write_failure_is_swallowed_with_one_log_line(tmp_path):
    logs = []
    log = ProgressLog(tmp_path / "no" / "such" / "progress.jsonl", lambda t, tag=None: logs.append(t))
    log.event(1, None, ["tile"], 0)
    log.event(2, None, ["tile"], 0)
    assert len(logs) == 1 and "progress log off" in logs[0] and not (tmp_path / "no").exists()


class Mash:
    name = "mash"

    def applies(self, ctx):
        return True

    def step(self, ctx):
        return Decision("B", "mash")


def test_heartbeat_rows_every_progress_log_every_steps(tmp_path):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6})
    mem = MapMemory(tmp_path / "maps.json")
    mem.m(0x28)["visited"]["5,6"] = 3  # stood here before: press 1 is no 'tile' progress either
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")
    engine = Engine(ctx, selector=Selector([Mash()]))
    for _ in range(PROGRESS_LOG_EVERY + 2):
        engine.step()
    rows = [json.loads(ln) for ln in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert rows == [{"step": PROGRESS_LOG_EVERY, "reasons": [], "since": PROGRESS_LOG_EVERY}]
    assert ctx.steps_since_progress == PROGRESS_LOG_EVERY + 2


def test_progress_and_ctx_steps_since_update_through_the_engine(tmp_path):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6})
    mem = MapMemory(tmp_path / "maps.json")  # never stood here: the first press IS 'tile' progress
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    ctx.trans = (tmp_path / "t.jsonl").open("a", encoding="utf-8")
    engine = Engine(ctx, selector=Selector([Mash()]))
    engine.step()
    assert ctx.steps_since_progress == 0  # the first press discovered the tile we stand on
    rows = [json.loads(ln) for ln in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert rows == [{"step": 1, "frame": 0, "reasons": ["tile"], "since": 0}]
    engine.step()
    assert ctx.steps_since_progress == 1  # same tile, same B: fruitless
