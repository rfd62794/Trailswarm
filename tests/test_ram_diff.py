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


def test_noise_is_learned_from_the_first_presses_and_applied_retroactively(tmp_path):
    emu = FakeEmulator()
    rd = RamDiffer(tmp_path / "ram_events.jsonl", warm=5, step_every=1)
    ctx = ctx_for(emu, tmp_path)
    for i in range(5):                                   # 0xC010 (a timer) changes on every one of the first presses
        rd.begin(ctx)
        emu.memory[0xC010] = i + 1; emu.memory[0xD362] = 100 + i
        rd.end(ctx, fr())
    assert offset(0xC010) in rd.noisy and offset(0xD362) in rd.noisy    # both change every press
    assert emu.frames == 0                                              # nothing was emulated to learn it
    rd.begin(ctx)
    emu.memory[0xC010] = 99; emu.memory[0xD400] = 7; emu.memory[0xD057] = 1   # battle starts
    rd.end(ctx, fr())
    rd.close()
    recs = [json.loads(x) for x in (tmp_path / "ram_events.jsonl").read_text().splitlines()]
    assert len(recs) == 6 and all(0xC010 not in {d[0] for d in r["d"]} for r in recs)
    assert {d[0] for d in recs[-1]["d"]} == {0xD400, 0xD057} and "battle_start" in recs[-1]["ev"]


def test_records_are_bounded(tmp_path):
    emu = FakeEmulator()
    rd = RamDiffer(tmp_path / "ram_events.jsonl", max_changed=5, max_records=3, warm=0)
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
    assert rd.off and rd.presses == 3                       # capped: later presses are not even snapshotted


def test_plain_presses_sampled_as_step(tmp_path):
    emu = FakeEmulator()
    rd = RamDiffer(tmp_path / "e.jsonl", step_every=4, warm=0)
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
    rd = RamDiffer(tmp_path / "e.jsonl", max_changed=3, step_every=1, warm=0)
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
    emu = FakeEmulator()
    rd = start_ram_diff(ctx, emu, run, str(st), "Pokemon Red.gb")
    emu_frames_unchanged = emu.frames == 0
    rd.close()
    assert ctx.ram_diff is rd and (run / "ram_start.state").read_bytes() == b"state-bytes"
    st.write_bytes(b"overwritten by a goal checkpoint")
    meta, _ = load_trace(run)
    assert meta["start"] == "cp" and meta["lead_ticks"] == 30 and emu_frames_unchanged
    assert start_state(meta, tmp_path, run) == run / "ram_start.state"


def test_recording_failures_never_raise(tmp_path):
    from pokeagent.explorer.ram_diff import start_ram_diff
    ctx = NS(ram_diff="x")
    assert start_ram_diff(ctx, FakeEmulator(), tmp_path / "missing" / "dir", None, "r.gb") is None and ctx.ram_diff is None
    emu = FakeEmulator()
    emu.on_press = None
    rd = RamDiffer(tmp_path / "e.jsonl", warm=0)
    rd.attach(emu)
    class Boom(FakeEmulator):
        def read_range(self, start, length):
            raise RuntimeError("emulator went away")
    rd.begin(NS(emu=Boom(), goal_steps={}))           # must not raise
    assert rd.off and emu.on_press is None            # recording switched itself off and detached the hook
    rd.end(NS(emu=emu, goal_steps={}, last_text="", step=1), fr())
    rd.close()


def test_trace_is_capped(tmp_path):
    emu = FakeEmulator(); emu.on_press = None; emu.frames = 0
    rd = RamDiffer(tmp_path / "e.jsonl", max_trace=3, warm=0)
    rd.attach(emu)
    for _ in range(3):
        emu.on_press(Button.A, 8, 16)
    assert rd.off and emu.on_press is None
    rd.close()
    assert len((tmp_path / "ram_trace.jsonl").read_text().splitlines()) == 1 + 3
