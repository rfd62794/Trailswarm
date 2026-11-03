from pokeagent.emulator import FakeEmulator
from pokeagent.hexmap import (
    WRAM_LEN,
    WRAM_START,
    Change,
    annotate,
    diff,
    exclude_noisy,
    find_consistent,
    snapshot,
)
from pokeagent.names import load_registry

X_OFFSET = 0xD362 - WRAM_START
TIMER_OFFSET = 0x10  # absolute 0xC010, outside every registry entry


def test_snapshot_reads_full_wram():
    fake = FakeEmulator({WRAM_START: 0xAA, WRAM_START + WRAM_LEN - 1: 0xBB})
    snap = snapshot(fake)
    assert len(snap) == WRAM_LEN
    assert snap[0] == 0xAA
    assert snap[-1] == 0xBB


def test_diff_reports_exactly_the_changed_bytes():
    before = bytes(WRAM_LEN)
    after = bytearray(before)
    after[X_OFFSET] = 4
    after[TIMER_OFFSET] = 9
    changes = diff(before, bytes(after))
    assert [(c.addr, c.old, c.new) for c in changes] == [
        (0xC010, 0, 9),
        (0xD362, 0, 4),
    ]


def test_diff_empty_when_identical():
    buf = bytes(WRAM_LEN)
    assert diff(buf, buf) == []


def test_find_consistent_delta_isolates_incrementing_address():
    snaps = []
    timers = [0, 1, 4, 5]  # +1, +3, +1: changes every step, not delta-consistent
    for i in range(4):
        buf = bytearray(WRAM_LEN)
        buf[X_OFFSET] = i
        buf[TIMER_OFFSET] = timers[i]
        snaps.append(bytes(buf))
    assert find_consistent(snaps, delta=1) == [0xD362]
    assert find_consistent(snaps) == [0xC010, 0xD362]
    assert find_consistent(snaps[:1]) == []


def test_exclude_noisy_collects_idle_changes():
    snaps = []
    for timer in [0, 5, 9]:
        buf = bytearray(WRAM_LEN)
        buf[TIMER_OFFSET] = timer
        snaps.append(bytes(buf))
    assert exclude_noisy(snaps) == {0xC010}
    assert exclude_noisy([snaps[0], snaps[0]]) == set()


def test_annotate_formats_named_and_unnamed():
    reg = load_registry()
    lines = annotate([Change(0xD362, 3, 4), Change(0xC010, 0, 9)], reg)
    assert lines == [
        "D362 wXCoord 03 -> 04 (3 -> 4)",
        "C010 - 00 -> 09 (0 -> 9)",
    ]
