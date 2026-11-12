"""read_party/read_party_count read RAM once per agent step (per emulator frame on emulators
without the step marker), not once per caller: the baseline profile counted ~12 party reads and
~3 real decodes per step."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.ramstructs import (
    PARTY_COUNT, PARTY_MON1, note_agent_step, read_party, read_party_count)


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


class _StepEmu:
    """An emulator carrying the agent-step marker like PyBoyEmulator: frames advance on tick/press
    but the party memo only re-reads when the step marker or ``_ram_rev`` moves."""

    agent_step = None  # class attr like PyBoyEmulator's: note_agent_step turns it into an int

    def __init__(self) -> None:
        self.memory = {PARTY_COUNT: 2, PARTY_MON1: 0x99, PARTY_MON1 + 33: 5,
                       PARTY_MON1 + 44: 0x42, PARTY_MON1 + 44 + 33: 7}
        self.frames = 0
        self._ram_rev = 0
        self.range_reads: list[int] = []
        self.reads: list[int] = []

    def read(self, addr):
        self.reads.append(addr)
        return self.memory.get(addr, 0)

    def read_range(self, addr, n):
        self.range_reads.append(addr)
        return bytes(self.memory.get(addr + i, 0) for i in range(n))

    def tick(self, n):
        self.frames += n

    def press(self, hold_frames=8, settle_frames=16):
        self.frames += hold_frames + settle_frames

    def set(self, addr, value):
        self.memory[addr] = value
        self._ram_rev += 1

    def party_decodes(self) -> int:
        return self.range_reads.count(PARTY_MON1)


def test_one_real_party_read_per_agent_step():
    """Frames and presses inside ONE agent step with no RAM write: exactly one real decode.
    Pre-change this was one decode per frame window - about 1.5 per press."""
    emu = _StepEmu()
    note_agent_step(emu)                       # Engine.step's bump: the decision cycle begins
    read_party(emu)                            # the step's one decode
    emu.press(); emu.tick(11)                  # the press ticks ~24 frames, no RAM write
    read_party(emu); read_party_count(emu)     # post-press readers share the step's decode
    emu.press(); emu.tick(13)
    read_party(emu)
    assert emu.party_decodes() == 1


def test_step_marker_write_and_load_state_each_re_read():
    emu = _StepEmu()
    note_agent_step(emu)
    read_party(emu)
    emu.press(); emu.tick(30)                  # frames moved, same step: still the memo
    read_party(emu)
    assert emu.party_decodes() == 1
    note_agent_step(emu)                       # the next agent step: fresh decode
    read_party(emu)
    assert emu.party_decodes() == 2
    emu.set(PARTY_MON1, 0x55)                  # an adapter write mid-step: re-read now
    assert read_party(emu)[0].species == 0x55
    assert emu.party_decodes() == 3
    emu._ram_rev += 1                          # what load_state does: same invalidation
    read_party(emu)
    assert emu.party_decodes() == 4


def test_engine_step_bumps_the_marker(tmp_path):
    """The wiring: Engine.step is what turns the marker on for a real run."""
    from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
    from pokeagent.explorer.engine import Engine
    from pokeagent.explorer.memory import MapMemory
    from pokeagent.explorer.selector import Selector

    emu = _StepEmu()
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"),
                          opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    Engine(ctx, selector=Selector([])).step()  # no behaviours: a wait step still marks the cycle
    assert emu.agent_step == 1
    Engine(ctx, selector=Selector([])).step()
    assert emu.agent_step == 2
