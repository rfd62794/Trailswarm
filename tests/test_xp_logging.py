"""XP/level logging: party snapshot + diff, battle record fields, levels.jsonl, the backfill formula."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import party_log
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import xp_backfill  # noqa: E402

COUNT, MON1, SIZE = 0xD163, 0xD16B, 44


def put_mon(mem: dict, slot: int, species: int, level: int, exp: int, hp: int, max_hp: int, moves=(33, 45, 0, 0)) -> None:
    base = MON1 + SIZE * slot
    raw = bytearray(SIZE)
    raw[0], raw[1], raw[2], raw[33], raw[34], raw[35] = species, hp >> 8, hp & 255, level, max_hp >> 8, max_hp & 255
    raw[8:12] = bytes(moves)
    raw[14:17] = exp.to_bytes(3, "big")
    for i, b in enumerate(raw):
        mem[base + i] = b


def party(*mons) -> dict:
    mem = {COUNT: len(mons)}
    for i, m in enumerate(mons):
        put_mon(mem, i, *m)
    return mem


def make_ctx(tmp_path, memory) -> ExplorerContext:
    emu = FakeEmulator(memory)
    return ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path)


def test_snapshot_rows_and_levelup_evolution_move():
    emu = FakeEmulator(party((153, 15, 2000, 30, 40, (33, 45, 0, 0)), (165, 5, 100, 10, 20)))
    before = party_log.snapshot(emu)
    assert party_log.rows(before) == [[153, 15, 2000, 30, 40], [165, 5, 100, 10, 20]]
    for a, v in party((9, 16, 2300, 12, 44, (33, 45, 22, 0)), (165, 5, 100, 10, 20)).items():
        emu.set(a, v)
    d = party_log.diff(before, party_log.snapshot(emu))
    assert d["exp_gained"] == [300, 0]
    assert d["level_ups"] == [{"slot": 0, "species": 9, "from": 15, "to": 16}]
    assert d["evolved"] == [{"slot": 0, "from": 153, "to": 9}]
    assert d["moves_learned"] == [{"slot": 0, "species": 9, "moves": [22]}]


def test_diff_no_change_is_empty():
    s = party_log.snapshot(FakeEmulator(party((153, 5, 135, 20, 20))))
    assert party_log.diff(s, s) == {"exp_gained": [0], "level_ups": [], "evolved": [], "moves_learned": []}


def test_end_battle_fields_and_levels_line(tmp_path):
    ctx = make_ctx(tmp_path, party((153, 5, 135, 20, 20)))
    ctx.step, ctx.frame = 40, 900
    log = party_log.of(ctx)
    log.start_battle(ctx)
    for a, v in party((153, 6, 180, 5, 24, (33, 45, 22, 0))).items():
        ctx.emu.set(a, v)
    fields = log.end_battle(ctx, won=True, fled=False)
    assert fields["party_before"] == [[153, 5, 135, 20, 20]] and fields["party_after"] == [[153, 6, 180, 5, 24]]
    assert fields["exp_gained"] == [45] and fields["level_ups"][0]["to"] == 6 and fields["moves_learned"][0]["moves"] == [22]
    line = json.loads((tmp_path / "levels.jsonl").read_text().splitlines()[-1])
    assert line["step"] == 40 and line["frame"] == 900 and line["cause"] == "battle_end" and line["party"] == [[153, 6, 180, 5, 24]]
    s = log.summary(ctx)
    assert s["exp_gained"] == 45 and s["levels_gained_by_slot"] == {"0": 1}


def test_out_of_battle_change_writes_levels_line(tmp_path):
    ctx = make_ctx(tmp_path, party((153, 5, 135, 20, 20)))
    log = party_log.of(ctx)
    log.tick(ctx)  # baseline
    log.tick(ctx)  # no change: no new line
    assert len((tmp_path / "levels.jsonl").read_text().splitlines()) == 1
    for a, v in party((153, 10, 1000, 20, 30)).items():  # a rare candy
        ctx.emu.set(a, v)
    ctx.step = 7
    log.tick(ctx)
    lines = [json.loads(x) for x in (tmp_path / "levels.jsonl").read_text().splitlines()]
    assert [x["cause"] for x in lines] == ["start", "out_of_battle"] and lines[1]["level_ups"][0]["to"] == 10


def test_battle_record_keeps_old_fields(tmp_path, monkeypatch):
    """The Battle behaviour's end-of-fight record: new fields added, old ones untouched."""
    from pokeagent.explorer.behaviours import Battle
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    mem = party((153, 5, 135, 20, 20))
    mem.update({0xD35E: 0x28, 0xD362: 5, 0xD361: 6, 0xD057: 0})
    ctx = make_ctx(tmp_path, mem)
    ctx.in_battle = True
    ctx.battle_pos = (0x28, 5, 6)
    ctx.battle_log = {"start": 3, "kind": 1, "you": [0, 8], "enemy": [165, 3], "enemy_species": 165, "turns": []}
    ctx.step = 15
    party_log.of(ctx).before = party_log.snapshot(ctx.emu)
    for a, v in party((153, 5, 150, 20, 20)).items():
        ctx.emu.set(a, v)
    ctx.refresh()
    Battle().step(ctx)
    rec = json.loads((tmp_path / "runs" / "battles.jsonl").read_text().splitlines()[-1])
    for k in ("start", "kind", "you", "enemy", "enemy_species", "end", "won", "run", "map", "presses", "hp_end", "fled", "turns"):
        assert k in rec
    assert rec["start"] == 3 and rec["end"] == 15 and rec["won"] is True
    assert rec["exp_gained"] == [15] and rec["party_before"][0][2] == 135 and rec["party_after"][0][2] == 150


def test_backfill_formula_on_synthetic_record(tmp_path):
    kb = {"dex_of_internal": {"165": 19}, "species_by_dex": {"19": {"name": "RATTATA", "base_exp": 57}}}
    wild = {"start": 1, "kind": 1, "enemy": [165, 7], "enemy_species": 165, "won": True, "run": "r", "map": 12}
    est = xp_backfill.estimate(wild, kb)
    assert est["exp_estimate"] == 57 and est["estimated"] is True
    assert xp_backfill.estimate({**wild, "kind": 2}, kb)["exp_estimate"] == int(57 * 7 * 1.5 // 7)
    assert xp_backfill.estimate({**wild, "won": False}, kb)["exp_estimate"] == 0
    assert xp_backfill.estimate({"kind": 1}, kb) is None
    src, out, kbp = tmp_path / "b.jsonl", tmp_path / "x.jsonl", tmp_path / "kb.json"
    src.write_text(json.dumps(wild) + "\nnot json\n")
    kbp.write_text(json.dumps(kb))
    assert xp_backfill.main(["--battles", str(src), "--kb", str(kbp), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["exp_estimate"] == 57


def test_xp_meter_failure_never_costs_the_battle_end_row(tmp_path, monkeypatch):
    from pokeagent.explorer import xp_meter

    def boom(self, ctx, before, after):
        raise RuntimeError("meter exploded")
    monkeypatch.setattr(xp_meter.XpMeter, "on_battle", boom)
    ctx = make_ctx(tmp_path, party((153, 5, 135, 20, 20)))
    log = party_log.of(ctx)
    log.start_battle(ctx)
    for a, v in party((153, 6, 180, 5, 24, (33, 45, 22, 0))).items():
        ctx.emu.set(a, v)
    fields = log.end_battle(ctx, won=True, fled=False)
    assert "party_error" not in fields and fields["exp_gained"] == [45] and fields["level_ups"][0]["to"] == 6
    line = json.loads((tmp_path / "levels.jsonl").read_text().splitlines()[-1])
    assert line["cause"] == "battle_end" and line["party"] == [[153, 6, 180, 5, 24]]
