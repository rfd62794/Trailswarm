"""Cross-run loop memory: folding vetoes into mem.data['loops'], activation at K runs, TTL, probes."""
import json
import time
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import loop_veto
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.loop_memory import (
    LOOP_PROMOTE_RUNS, LOOP_RUNS_KEPT, LOOP_TTL_DAYS, PROBE_EVERY, active, fold_shared,
)
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.selector import Selector

NOW = 1_700_000_000
KEY = "35,5,20,A"
MAP, PX, PY = 0xD35E, 0xD362, 0xD361


def entry(runs, last=NOW, clear=0):
    return {"runs": list(runs), "last": last, "clear": clear}


def make_ctx(tmp_path, loops=None, step=0):
    emu = FakeEmulator({MAP: 35, PX: 5, PY: 20})
    mem = MapMemory(tmp_path / "maps.json")
    if loops is not None:
        mem.data["loops"] = loops
    rdir = tmp_path / "run-x"
    rdir.mkdir(exist_ok=True)
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(), run_dir=rdir, stable_frames=10, step=step)
    ctx.refresh()
    return ctx


class Alt:
    name = "mover"

    def applies(self, ctx):
        return True

    def step(self, ctx):
        return Decision("DOWN", "alt_rule")


class Talker:
    name = "talker"

    def applies(self, ctx):
        return True

    def step(self, ctx):
        return Decision("A", "talk_rule")


def rows(ctx):
    path = Path(ctx.run_dir) / "loops.jsonl"
    return [json.loads(ln) for ln in path.read_text().splitlines()] if path.exists() else []


def test_fold_records_this_run_once_and_refreshes_last():
    data = {}
    assert fold_shared(data, [KEY], "run-a", NOW) == []
    e = data["loops"][KEY]
    assert e == {"runs": ["run-a"], "last": NOW, "clear": 0}
    fold_shared(data, [KEY], "run-a", NOW + 10)  # the same run again: one entry, newer last
    assert data["loops"][KEY] == {"runs": ["run-a"], "last": NOW + 10, "clear": 0}


def test_entry_activates_only_at_k_distinct_runs():
    data = {}
    for i in range(LOOP_PROMOTE_RUNS - 1):
        fold_shared(data, [KEY], f"run-{i}", NOW)
    assert not active(data["loops"][KEY], NOW)
    fold_shared(data, [KEY], "run-last", NOW)
    assert active(data["loops"][KEY], NOW)


def test_ttl_expires_and_clear_deactivates():
    e = entry([f"r{i}" for i in range(LOOP_PROMOTE_RUNS)])
    assert active(e, NOW + LOOP_TTL_DAYS * 86400 - 1)
    assert not active(e, NOW + LOOP_TTL_DAYS * 86400)   # stale: a fixed bug stops being vetoed
    e["clear"], e["last"] = NOW + 1, NOW + 1
    assert not active(e, NOW + 2)                        # last > clear fails


def test_fold_drops_stale_and_malformed_entries():
    data = {"loops": {KEY: entry(["a", "b", "c"], last=NOW - LOOP_TTL_DAYS * 86400),
                      "bad": {"runs": 5, "last": 1, "clear": 0}}}
    assert set(fold_shared(data, [], "run-b", NOW)) == {KEY, "bad"} and data["loops"] == {}


def test_runs_list_is_capped_to_newest_kept():
    data = {"loops": {KEY: entry([f"r{i}" for i in range(LOOP_RUNS_KEPT)])}}
    fold_shared(data, [KEY], "newest", NOW)
    assert data["loops"][KEY]["runs"] == [f"r{i}" for i in range(1, LOOP_RUNS_KEPT)] + ["newest"]


def test_active_shared_entry_probes_once_then_vetoes_on_sight(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    ctx = make_ctx(tmp_path, loops={KEY: entry([f"r{i}" for i in range(LOOP_PROMOTE_RUNS)], last=NOW)})
    sel = Selector([Alt()])
    d = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
    assert d.button == "A"                                   # first sight = the one probe of the window
    loop_veto.record(ctx, Decision("A", "talk_rule", behaviour="talker"), [])
    d2 = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
    assert d2.button == "DOWN" and d2.behaviour == "mover"   # inside the window: dead on sight, re-chosen
    kinds = [r["kind"] for r in rows(ctx)]
    assert kinds == ["probe", "promote", "veto"] and rows(ctx)[-1]["source"] == "shared"


def test_probe_spacing_and_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    loops = {KEY: entry(["a", "b", "c"], last=NOW)}
    ctx = make_ctx(tmp_path, loops=loops)
    sel = Selector([Alt()])
    d = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
    assert d.button == "A" and loop_veto.of(ctx).probe_key == KEY   # first probe lets it through
    loop_veto.record(ctx, Decision("A", "talk_rule", behaviour="talker"), ["tile"])
    assert loops[KEY]["clear"] == NOW                                # it worked: alive again
    loops[KEY]["clear"] = 0
    ctx.step = PROBE_EVERY + 10
    d = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
    assert d.button == "A"                                           # next probe window: through once
    loop_veto.record(ctx, Decision("A", "talk_rule", behaviour="talker"), [])
    assert loops[KEY]["clear"] == 0 and active(loops[KEY], NOW)      # failed probe: still active
    ctx.step = PROBE_EVERY + 20
    d = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
    assert d.button == "DOWN"                                        # inside the window: vetoed, no second probe
    assert [r["ok"] for r in rows(ctx) if r["kind"] == "probe"] == [True, False]


def test_fold_promotes_this_runs_dead_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    ctx = make_ctx(tmp_path)
    sel = Selector([Alt()])
    for i in range(1, 5):  # three fruitless A presses, then the vetoed step picks DOWN
        d = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
        ctx.step = i
        loop_veto.record(ctx, d, [])
    loop_veto.fold(ctx)
    e = ctx.mem.data["loops"]["35,5,20,A"]
    assert e["runs"] == ["run-x"] and e["last"] == NOW and e["clear"] == 0


def test_expire_rows_for_stale_shared_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    ctx = make_ctx(tmp_path, loops={"9,1,1,B": entry(["a", "b", "c"], last=NOW - LOOP_TTL_DAYS * 86400)})
    loop_veto.fold(ctx)
    assert "9,1,1,B" not in ctx.mem.data["loops"]
    assert rows(ctx) == [{"step": 0, "kind": "expire", "key": "9,1,1,B", "source": "shared"}]


def test_finish_writes_the_ledger_row(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW)
    ctx = make_ctx(tmp_path)
    sel = Selector([Alt()])
    for i in range(1, 5):
        d = loop_veto.check(ctx, sel, Decision("A", "talk_rule", behaviour="talker"))
        ctx.step = i
        loop_veto.record(ctx, d, [])
    loop_veto.finish(ctx)
    last = rows(ctx)[-1]
    assert last["kind"] == "ledger" and last["top"][0]["button"] == "A" and last["top"][0]["vetoes"] >= 1
