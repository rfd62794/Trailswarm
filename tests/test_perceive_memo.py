"""read_party/read_party_count read RAM once per emulator frame, not once per caller: the baseline
profile counted ~6 party reads per step, every one decoding identical bytes."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.ramstructs import PARTY_COUNT, PARTY_MON1, read_party, read_party_count


def _emu() -> FakeEmulator:
    # party of 2: slot 0 species 0x99 level 5, slot 1 species 0x42 level 7
    return FakeEmulator({PARTY_COUNT: 2, PARTY_MON1: 0x99, PARTY_MON1 + 33: 5,
                         PARTY_MON1 + 44: 0x42, PARTY_MON1 + 44 + 33: 7})


def _range_reads(emu) -> list:
    orig = emu.read_range
    calls = []

    def counted(addr, n):
        calls.append(addr)
        return orig(addr, n)

    emu.read_range = counted
    return calls


def test_party_is_read_once_per_frame():
    emu = _emu()
    calls = _range_reads(emu)
    p1, p2 = read_party(emu), read_party(emu)
    assert calls.count(PARTY_MON1) == 1  # one RAM read for two calls in the same frame
    assert [m.species for m in p1] == [0x99, 0x42] and p1 == p2
    p1.append(p1[0])
    assert len(read_party(emu)) == 2  # callers get a copy; the memo stays intact


def test_a_tick_re_reads_and_a_write_re_reads_too():
    emu = _emu()
    calls = _range_reads(emu)
    read_party(emu)
    emu.tick(10)
    read_party(emu)
    assert calls.count(PARTY_MON1) == 2  # a press ticks forward: post-press reads are fresh
    emu.set(PARTY_MON1, 0x55)
    assert read_party(emu)[0].species == 0x55  # a RAM write invalidates without a tick
    emu.memory[PARTY_MON1 + 44] = 0x77  # even a direct memory poke invalidates
    assert read_party(emu)[1].species == 0x77


def test_party_count_memoized_per_frame():
    emu = _emu()
    reads = []
    orig = emu.read

    def counted(addr):
        reads.append(addr)
        return orig(addr)

    emu.read = counted
    assert read_party_count(emu) == 2 == read_party_count(emu)
    assert reads.count(PARTY_COUNT) == 1
    emu.tick(4)
    read_party_count(emu)
    assert reads.count(PARTY_COUNT) == 2


def test_emulator_without_frames_bypasses_the_memo():
    class Stub:  # no .frames at all: a stub emulator must not be cached
        def __init__(self):
            self.memory = {PARTY_COUNT: 1, PARTY_MON1: 0x99}

        def read(self, addr):
            return self.memory.get(addr, 0)

        def read_range(self, addr, n):
            return bytes(self.memory.get(addr + i, 0) for i in range(n))

    emu = Stub()
    assert read_party(emu)[0].species == 0x99
    emu.memory[PARTY_MON1] = 0x42
    assert read_party(emu)[0].species == 0x42  # every call re-reads: no frames counter, no cache
