"""XP meter: window math, identity across re-orders, jsonl rows, the spot ledger, the console line (synthetic parties)."""
from __future__ import annotations

import json
from types import SimpleNamespace

from pokeagent.explorer import xp_meter, xp_report, xp_spots
from pokeagent.explorer.context import Frame
from pokeagent.explorer.perceive import TILEMAP_LEN
from pokeagent.emulator import FakeEmulator

MOVES = (33, 0, 0, 0)
A, B = (1, 11), (2, 22)
ROUTE24 = 35


def mon(species, level, exp, ident):
    return (species, level, exp, 10, 20, MOVES, ident)


def make_ctx(tmp_path, step=0, m=ROUTE24):
    ctx = SimpleNamespace(step=step, view=Frame(m, 1, 1, bytes(TILEMAP_LEN)), run_dir=tmp_path, logs=[], emu=FakeEmulator({}), xp_meter=None)
    ctx.log = lambda t, tag=None: ctx.logs.append(t)
    return ctx


def run(ctx, meter, steps):
    for _ in range(steps):
        ctx.step += 1
        meter.tick(ctx)


def rows_of(tmp_path):
    return [json.loads(x) for x in (tmp_path / "xp_rates.jsonl").read_text().splitlines()]


def test_window_math_and_row_shape(tmp_path):
    ctx, meter = make_ctx(tmp_path), xp_meter.XpMeter(window=1000, spots=xp_spots.XpSpots(path=tmp_path / "s.json"))
    run(ctx, meter, 1)
    before = [mon(165, 8, 100, A), mon(176, 9, 200, B)]
    after = [mon(165, 8, 100, A), mon(176, 9, 262, B)]
    for _ in range(2):  # B (slot 1, not the starting lead) gains 62 twice
        meter.on_battle(ctx, before, after)
    run(ctx, meter, 999)
    rows = [r for r in rows_of(tmp_path) if r["member"] == "0002-0016"]
    assert len(rows) == 1
    r = rows[0]
    assert r["xp_gain"] == 124 and r["steps"] == 1000 and r["battles"] == 2 and r["map"] == ROUTE24
    assert r["xp_per_1k_steps"] == 124.0 and r["xp_per_battle"] == 62.0
    assert (r["species"], r["level"], r["solo"], r["switched"], r["kind"]) == (176, 9, 0, 2, "window")
    assert {"step", "member", "species", "level", "xp_gain", "steps", "battles", "map", "xp_per_1k_steps"} <= set(r)
    idle = [r for r in rows_of(tmp_path) if r["member"] == "0001-000b"][0]
    assert idle["xp_gain"] == 0 and idle["xp_per_1k_steps"] == 0.0


def test_identity_survives_reorder(tmp_path):
    ctx, meter = make_ctx(tmp_path, step=1), xp_meter.XpMeter(window=10, spots=xp_spots.XpSpots(path=tmp_path / "s.json"))
    meter.on_battle(ctx, [mon(165, 8, 100, A), mon(176, 9, 200, B)], [mon(165, 8, 100, A), mon(176, 9, 250, B)])
    meter.on_battle(ctx, [mon(176, 9, 250, B), mon(165, 8, 100, A)], [mon(176, 9, 300, B), mon(165, 8, 100, A)])  # slots swapped
    assert meter.acc["0002-0016"]["xp"] == 100 and meter.acc["0002-0016"]["battles"] == 2
    assert "0001-000b" not in meter.acc or meter.acc["0001-000b"]["xp"] == 0
    assert meter.acc["0002-0016"]["solo"] == 1 and meter.acc["0002-0016"]["switched"] == 1  # 2nd fight: B was the lead
    assert meter.acc["0002-0016"]["solo"] + meter.acc["0002-0016"]["switched"] == 2


def test_ledger_rolling_average_and_bounds(tmp_path):
    sp = xp_spots.XpSpots(path=tmp_path / "s.json")
    sp.record(ROUTE24, 9, 100, 10, 10)
    c = sp.record(ROUTE24, 7, 200, 20, 10)  # same band 5-9
    assert c["n"] == 2 and c["xp_per_1k"] == round(100 * 0.7 + 200 * 0.3, 3)
    sp.record(ROUTE24, 12, 50, 5, 10)
    assert sp.best_by_band() == {"5-9": {"map": ROUTE24, "xp_per_1k": 130.0, "n": 2}, "10-14": {"map": ROUTE24, "xp_per_1k": 50.0, "n": 1}}
    for i in range(xp_spots.MAX_SPOTS + 50):
        sp.record(1000 + i, 9, 1, 1, 1)
    assert len(sp.spots) == xp_spots.MAX_SPOTS and f"{ROUTE24}|5-9" in sp.spots  # the well-measured cell survives eviction
    assert sp.save() and xp_spots.XpSpots.load(tmp_path / "s.json").spots == sp.spots
    assert xp_spots.XpSpots.load(tmp_path / "missing.json").spots == {}


def test_window_feeds_ledger_and_finish_writes_map_summary(tmp_path):
    path = tmp_path / "s.json"
    ctx, meter = make_ctx(tmp_path), xp_meter.XpMeter(window=500, spots=xp_spots.XpSpots(path=path))
    run(ctx, meter, 1)
    meter.on_battle(ctx, [mon(176, 9, 200, B)], [mon(176, 9, 300, B)])
    run(ctx, meter, 499)
    assert xp_report.best_spots(path)["5-9"]["map"] == ROUTE24
    meter.on_battle(ctx, [mon(176, 9, 300, B)], [mon(176, 10, 330, B)])
    run(ctx, meter, 10)
    meter.finish(ctx)
    summ = [r for r in rows_of(tmp_path) if r["kind"] == "map_summary"]
    assert len(summ) == 1 and summ[0]["map"] == ROUTE24 and summ[0]["xp"] == 130 and summ[0]["battles"] == 2


def test_write_failure_never_raises(tmp_path):
    ctx = make_ctx(tmp_path / "nope")
    meter = xp_meter.XpMeter(window=2, spots=xp_spots.XpSpots(path=tmp_path / "nodir" / "x" / "s.json"))
    meter.on_battle(ctx, [mon(176, 9, 1, B)], [mon(176, 9, 9, B)])
    run(ctx, meter, 5)
    meter.finish(ctx)


def test_console_line_format_and_rate_limit(tmp_path):
    row = {"kind": "window", "species": 1, "level": 9, "xp_gain": 412, "xp_per_1k_steps": 412.0, "map": ROUTE24, "solo": 0, "switched": 3}
    line = xp_report.console_line([row])
    assert line.startswith("[xp] ") and " L9 +412 xp/1k steps on " in line and line.endswith("(solo 0%, switched 100%)")
    assert xp_report.console_line([{**row, "xp_gain": 0}]) is None
    ctx, meter = make_ctx(tmp_path, step=10), xp_meter.XpMeter(window=10, spots=xp_spots.XpSpots(path=tmp_path / "s.json"))
    meter.on_battle(ctx, [mon(176, 9, 1, B)], [mon(176, 9, 99, B)])
    meter._console(ctx, xp_meter_rows := [row]); meter._console(ctx, xp_meter_rows)
    assert len([x for x in ctx.logs if x.startswith("[xp]")]) == 1
