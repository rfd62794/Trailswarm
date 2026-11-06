import json
from types import SimpleNamespace as NS

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.explorer.ram_diff import RamDiffer, changed_offsets, snapshot
from pokeagent.explorer.ram_event_kinds import SNAP_LEN, addr_of, classify, offset


def fr(**kw):
    base = dict(extra={}, box_before=False, box_after=False, tm=b"", tm2=b"", text="", after=(12, 5, 6))
    base.update(kw)
    return NS(**base)


def ctx_for(emu, tmp):
    return NS(emu=emu, goal_steps={}, last_text="", step=1)


def test_offset_roundtrip_and_snapshot_len():
    assert SNAP_LEN == 0x2000 + 0x7F
    for a in (0xC000, 0xDFFF, 0xFF80, 0xFFFE):
        assert addr_of(offset(a)) == a
    assert len(snapshot(FakeEmulator())) == SNAP_LEN


def test_changed_offsets_finds_exact_bytes():
    a = bytearray(SNAP_LEN); b = bytearray(a)
    b[5] = 1; b[SNAP_LEN - 1] = 9
    assert changed_offsets(bytes(a), bytes(b)) == [5, SNAP_LEN - 1]
    assert changed_offsets(bytes(a), bytes(a)) == []


def test_noise_learning_drops_always_changing_bytes(tmp_path):
    class Ticker(FakeEmulator):
        def tick(self, n):
            self.memory[0xC010] = (self.memory.get(0xC010, 0) + 1) % 256   # a frame timer
            super().tick(n)
    emu = Ticker()
    rd = RamDiffer(tmp_path / "ram_events.jsonl")
    assert rd.learn_noise(emu, rounds=10) == 1
    assert offset(0xC010) in rd.noisy
    ctx = ctx_for(emu, tmp_path)
    rd.begin(ctx)
    emu.memory[0xC010] += 1; emu.memory[0xD400] = 7
    emu.memory[0xD057] = 1                              # battle starts: an event
    rd.end(ctx, fr())
    rd.close()
    recs = [json.loads(x) for x in (tmp_path / "ram_events.jsonl").read_text().splitlines() if '"ev"' in x]
    addrs = {d[0] for d in recs[0]["d"]}
    assert 0xC010 not in addrs and {0xD400, 0xD057} <= addrs
    assert "battle_start" in recs[0]["ev"]


def test_records_are_bounded(tmp_path):
    emu = FakeEmulator()
    rd = RamDiffer(tmp_path / "ram_events.jsonl", max_changed=5, max_records=3)
    ctx = ctx_for(emu, tmp_path)
    for i in range(6):
        rd.begin(ctx)
        for k in range(20):
            emu.memory[0xD100 + k] = i + 1
        emu.memory[0xD347] = i + 1                      # money event
        rd.end(ctx, fr())
    rd.close()
    recs = [json.loads(x) for x in (tmp_path / "ram_events.jsonl").read_text().splitlines()]
    assert len(recs) == 3
    assert all(len(r["d"]) <= 5 and r["n"] > 5 for r in recs)


def test_plain_presses_sampled_as_step(tmp_path):
    emu = FakeEmulator()
    rd = RamDiffer(tmp_path / "e.jsonl", step_every=4)
    ctx = ctx_for(emu, tmp_path)
    for i in range(8):
        rd.begin(ctx); emu.memory[0xD362] = i; rd.end(ctx, fr())
    rd.close()
    recs = [json.loads(x) for x in (tmp_path / "e.jsonl").read_text().splitlines()]
    assert [r["ev"] for r in recs] == [["step"], ["step"]]


def test_classify_events():
    pre = bytearray(SNAP_LEN); post = bytearray(SNAP_LEN)
    post[offset(0xD057)] = 2; post[offset(0xCFE5)] = 165
    post[offset(0xD35E)] = 12; pre[offset(0xD35E)] = 0
    ev, vals = classify(bytes(pre), bytes(post), fr(extra={"item": {"id": 20, "delta": 1}}, box_after=True), 1)
    assert {"battle_start", "map_change", "item_gain", "goal", "text_open"} <= set(ev)
    assert vals["enemy_species"] == 165 and vals["map"] == 12 and vals["item"] == 20


def test_emulator_press_hook_and_trace(tmp_path):
    emu = FakeEmulator()
    emu.on_press = None
    rd = RamDiffer(tmp_path / "e.jsonl")
    rd.attach(emu)  # FakeEmulator has no frames: hook just installed
    emu.frames = 0
    emu.on_press(Button.A, 8, 16)
    rd.close()
    lines = (tmp_path / "ram_trace.jsonl").read_text().splitlines()
    assert json.loads(lines[1]) == [0, "a", 8, 16]


def test_truncation_keeps_the_rarest_bytes(tmp_path):
    emu = FakeEmulator()
    rd = RamDiffer(tmp_path / "e.jsonl", max_changed=3, step_every=1)
    ctx = ctx_for(emu, tmp_path)
    for i in range(5):                                   # 0xC000-0xC009 change on every press: common
        rd.begin(ctx)
        for k in range(10):
            emu.memory[0xC000 + k] = i + 1
        rd.end(ctx, fr())
    rd.begin(ctx)
    for k in range(10):
        emu.memory[0xC000 + k] = 99
    emu.memory[0xD500] = 1; emu.memory[0xD501] = 1; emu.memory[0xD347] = 5   # three rare bytes + money event
    rd.end(ctx, fr())
    rd.close()
    last = json.loads((tmp_path / "e.jsonl").read_text().splitlines()[-1])
    assert [d[0] for d in last["d"]] == [0xD347, 0xD500, 0xD501]


def test_start_ram_diff_keeps_a_private_copy_of_the_start_state(tmp_path):
    from pokeagent.explorer.ram_diff import start_ram_diff
    from pokeagent.ramlab.replay import load_trace, start_state
    st = tmp_path / "cp.state"; st.write_bytes(b"state-bytes")
    run = tmp_path / "run"; run.mkdir()
    ctx = NS(ram_diff=None)
    rd = start_ram_diff(ctx, FakeEmulator(), run, str(st), "Pokemon Red.gb")
    rd.close()
    assert ctx.ram_diff is rd and (run / "ram_start.state").read_bytes() == b"state-bytes"
    st.write_bytes(b"overwritten by a goal checkpoint")
    meta, _ = load_trace(run)
    assert meta["start"] == "cp" and meta["lead_ticks"] == 30
    assert start_state(meta, tmp_path, run) == run / "ram_start.state"
