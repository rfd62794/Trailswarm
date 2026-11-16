"""The standalone step runner: schema validation, ordered presses, one trace row per step with
the probe dict, until predicates (reached true/false at the cap), the total-press budget abort,
and the no-RAM-write guarantee - all on FakeEmulator, no ROM."""
from __future__ import annotations

import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.glitchlab import script as gs


class TimelineEmu(FakeEmulator):
    """Flips a RAM byte after the Nth press call (NONE presses count too), so until
    predicates can be exercised."""

    def __init__(self, memory=None, flips=()):
        super().__init__(memory)
        self._flips = dict(flips)   # press-call count -> (addr, value)
        self._n = 0

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        self._n += 1
        hit = self._flips.get(self._n)
        if hit:
            self.set(*hit)


def test_load_script_rejects_unknown_keys_buttons_oversize_and_bad_shapes():
    with pytest.raises(ValueError):
        gs.load_script([{"id": "a", "press": ["A"], "bogus": 1}])                       # unknown key
    with pytest.raises(ValueError):
        gs.load_script([{"id": "a", "press": ["JUMP"]}])                              # unknown button
    with pytest.raises(ValueError):
        gs.load_script([{"id": "a", "press": ["A"] * (gs.MAX_PRESSES_PER_STEP + 1)}])  # over-long list
    with pytest.raises(ValueError):
        gs.load_script([{"id": "a", "wait": gs.MAX_WAIT_FRAMES + 1}])                 # over-long wait
    with pytest.raises(ValueError):
        gs.load_script([{"id": "a", "until": {"addr": "0xD057", "equals": 2}}])       # until w/o press
    with pytest.raises(ValueError):
        gs.load_script([{"id": "a", "press": ["A"], "mark": True}])                   # two actions
    with pytest.raises(ValueError):
        gs.load_script("not a list")
    with pytest.raises(ValueError):
        gs.load_script([{"press": ["A"]}])                                          # no id


def test_run_script_presses_in_order_and_emits_one_probe_row_per_step():
    emu = FakeEmulator({0xD057: 7})
    steps = gs.load_script([{"id": "w", "press": ["RIGHT", "RIGHT"], "hold": 4, "settle": 2},
                            {"id": "m", "mark": True},
                            {"id": "x", "wait": 12}])
    rows = gs.run_script(emu, steps, lambda e: {"battle": e.read(0xD057)})
    assert emu.presses == [Button.RIGHT, Button.RIGHT]
    assert [(r["i"], r["id"]) for r in rows] == [(0, "w"), (1, "m"), (2, "x")]
    assert all(r["ram"] == {"battle": 7} for r in rows)
    assert rows[0]["reached"] is None and rows[0]["presses"] == 2
    assert rows[-1]["presses"] == 2 and rows[-1]["frames"] == emu.frames == 24


def test_until_repeats_until_the_byte_matches_then_reports_reached():
    emu = TimelineEmu(flips={3: (0xD057, 2)})
    steps = gs.load_script([{"id": "u", "until": {"addr": "0xD057", "equals": 2},
                             "press": ["NONE"], "max_presses": 10}])
    rows = gs.run_script(emu, steps, lambda e: {})
    assert rows[0]["reached"] is True and rows[0]["presses"] == 3


def test_until_already_satisfied_presses_nothing_and_reports_reached():
    emu = TimelineEmu({0xD057: 2})
    steps = gs.load_script([{"id": "u", "until": {"addr": "0xD057", "equals": 2},
                             "press": ["A"], "max_presses": 10}])
    rows = gs.run_script(emu, steps, lambda e: {})
    assert rows[0]["reached"] is True and rows[0]["presses"] == 0 and emu.presses == []


def test_until_reports_unreached_at_the_step_press_cap():
    emu = TimelineEmu()
    steps = gs.load_script([{"id": "u", "until": {"addr": "0xD057", "equals": 2},
                             "press": ["A", "B"], "max_presses": 3}])
    rows = gs.run_script(emu, steps, lambda e: {})
    assert rows[0]["reached"] is False and rows[0]["presses"] == 3
    assert emu.presses == [Button.A, Button.B, Button.A]


def test_total_press_budget_ends_the_run_with_an_abort_row(monkeypatch):
    monkeypatch.setattr(gs, "MAX_TOTAL_PRESSES", 5)
    emu = FakeEmulator()
    steps = gs.load_script([{"id": f"s{i}", "press": ["A"] * 3} for i in range(4)])
    rows = gs.run_script(emu, steps, lambda e: {})
    assert [r["id"] for r in rows] == ["s0", "s1"]          # s1 aborted on its third press
    assert rows[-1]["aborted"] == "budget" and rows[-1]["presses"] == 5
    assert len(emu.presses) == 5


def test_run_script_never_writes_ram():
    emu = FakeEmulator()

    def boom(*_a):
        raise AssertionError("emu.write called")

    emu.write = boom
    steps = gs.load_script([{"id": "a", "press": ["A"]}, {"id": "w", "wait": 5}, {"id": "m", "mark": True}])
    rows = gs.run_script(emu, steps, lambda e: {"x": e.read(0)})
    assert len(rows) == 3 and emu.memory.get(0, 0) == 0


def test_record_streams_each_row_as_it_lands():
    emu = FakeEmulator()
    seen = []
    steps = gs.load_script([{"id": "a", "press": ["A"]}, {"id": "m", "mark": True}])
    rows = gs.run_script(emu, steps, lambda e: {}, record=seen.append)
    assert seen == rows
