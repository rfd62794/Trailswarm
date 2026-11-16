"""The checkpoint guard: read-only, refuses a write while a glitch signature is active and records the
refusal; a broken emulator never blocks a write. Covers the press_goals / press_stop / LegStateSaver call
sites and the fingerprint's new keys (synthetic fakes, no ROM)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pokeagent import campaign, glitch_guard, statefp
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import press_goals, press_stop
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.goals import GOALS
from pokeagent.legs import states as S
from pokeagent.novelty import discoveries as dc

VFS = 0xD618  # glitch_signals.VIRIDIAN_FOREST_SCRIPT


# --- the guard itself -----------------------------------------------------------------------------------
def test_clean_ram_allows_the_write_and_logs_nothing(tmp_path):
    logs = []
    assert glitch_guard.allow_write(FakeEmulator({}), "goal:x", runs_dir=tmp_path, run="r", log=logs.append)
    assert logs == [] and not (tmp_path / dc.LOG_NAME).exists()


def test_active_signature_refuses_and_records_a_discovery(tmp_path):
    emu = FakeEmulator({VFS: 6})
    logs = []
    assert glitch_guard.allow_write(emu, "goal:x", runs_dir=tmp_path, run="r", log=logs.append) is False
    rec = json.loads((tmp_path / dc.LOG_NAME).read_text().splitlines()[0])
    assert (rec["kind"], rec["feature"]) == ("checkpoint_refused", "script_oor")
    assert rec["after"]["what"] == "goal:x" and rec["after"]["forest_script"] == 6
    assert list((tmp_path / dc.DIR_NAME).glob(f"*{dc.STATE_SUFFIX}"))
    assert "checkpoint refused" in logs[0] and "script_oor" in logs[0]


def test_a_broken_emulator_allows_the_write_instead_of_raising(tmp_path):
    class Dead:
        def read(self, a):
            raise OSError("gone")

    assert glitch_guard.allow_write(Dead(), "x", runs_dir=tmp_path) is True


# --- streak: the guard shares the detectors' persistence ------------------------------------------------------
def _drive(lg, emu, sig_snap, n):
    """Feed ``n`` consecutive identical snapshots through the discovery detectors (which publish the streaks)."""
    for step in range(n):
        lg.check(sig_snap, sig_snap, step, emu, {"counts": {}, "maps_known": True, "stage": {}, "seen_species": set(),
                                                 "stage_now": None})


def test_a_single_snapshot_blip_does_not_refuse(tmp_path):
    from pokeagent import glitch_signals as gs
    from pokeagent.novelty.features import Snapshot
    for byte, fields in ((gs.MOVE_OVERRIDE, {"move_override": 1}), (gs.MISC_FLAGS, {"misc_flags": 1})):
        emu = FakeEmulator({byte: 1})
        _drive(dc.DiscoveryLog(tmp_path, "r", "explorer"), emu, Snapshot(sig=gs.Signals(**fields).as_tuple()), 1)
        assert glitch_guard.allow_write(emu, "goal:x", runs_dir=tmp_path, run="r") is True
        assert not (tmp_path / dc.LOG_NAME).exists()


def test_a_held_streak_refuses_and_a_gap_clears_it(tmp_path):
    from pokeagent import glitch_signals as gs
    from pokeagent.novelty.features import Snapshot
    emu = FakeEmulator({gs.MOVE_OVERRIDE: 1})
    lg = dc.DiscoveryLog(tmp_path, "r", "explorer")
    blip = Snapshot(sig=gs.Signals(move_override=1).as_tuple())
    _drive(lg, emu, blip, dc.STUCK_STEPS - 1)
    assert glitch_guard.allow_write(emu, "goal:x", runs_dir=tmp_path, run="r") is True      # 29: still a blip
    _drive(lg, emu, blip, 1)
    assert glitch_guard.allow_write(emu, "goal:x", runs_dir=tmp_path, run="r") is False     # 30: refused
    rec = json.loads((tmp_path / dc.LOG_NAME).read_text().splitlines()[-1])
    assert (rec["kind"], rec["feature"]) == ("checkpoint_refused", "move_override")
    _drive(lg, FakeEmulator(), Snapshot(sig=gs.Signals().as_tuple()), 1)                    # a clean snapshot resets
    emu2 = FakeEmulator({gs.MOVE_OVERRIDE: 1})
    gs.share_streaks(emu2, lg.streaks)
    assert glitch_guard.allow_write(emu2, "goal:y", runs_dir=tmp_path, run="r") is True


# --- call sites ------------------------------------------------------------------------------------------
class LegEmu:
    """The minimal emu legs.states.calm reads: a healthy one-mon party plus optional glitch bytes."""

    def __init__(self, extra=None):
        self.mem = {0xD057: 0, 0xD163: 1, 0xD164: 0x99, 0xD16B: 0x99,
                    0xD16C: 0, 0xD16D: 20, 0xD18D: 0, 0xD18E: 20}
        self.mem.update(extra or {})
        self.saves = 0

    def read(self, a):
        return self.mem.get(a, 0)

    def read_range(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def save_state(self, path):
        self.saves += 1
        Path(path).write_bytes(b"s")


def leg_ctx(emu, tmp_path):
    c = SimpleNamespace(emu=emu, run_dir=tmp_path / "run-1", logs=[], opts=SimpleNamespace(starter="x"))
    c.log = lambda t, tag=None: c.logs.append(t)
    return c


def entry(after):
    return PressFrame("RIGHT", "agent", "", before=(1, 0, 0), after=after, box_after=False)


def test_leg_state_saver_skips_the_write_while_active_and_retries_when_clean(tmp_path):
    sv = S.LegStateSaver(tmp_path / "s")
    assert sv.observe(leg_ctx(LegEmu({VFS: 6}), tmp_path), entry((2, 5, 6))) is None
    assert not (tmp_path / "s").exists() and (2, 5, 6) not in sv.done      # not marked: a later press retries
    ctx = leg_ctx(LegEmu(), tmp_path)
    p = sv.observe(ctx, entry((2, 5, 6)))
    assert p == tmp_path / "s" / "2_5_6.state" and p.exists()


def test_record_goals_skips_the_checkpoint_but_keeps_the_goal_and_milestone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    unverified = [g for g in GOALS if campaign.is_unverified(g)]
    real = next(g for g in GOALS if not campaign.is_unverified(g) and GOALS.index(g) > GOALS.index(unverified[0]))
    state = {g: False for g in GOALS}
    state[real] = True
    monkeypatch.setattr(press_goals, "check_goals", lambda e, c: dict(state))
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text("{}")
    ctx = SimpleNamespace(emu=FakeEmulator({VFS: 6}), run_dir=run, step=7, frame=70, goal_steps={},
                          initial_goals=set(), initial_goals_ready=True, goal_left_house=False,
                          log=lambda m, t=None: None,
                          opts=SimpleNamespace(state_stem="", stop_at_goal=None, stop_at_map=None,
                                               headless=False, starter="x"))
    press_goals.record_goals(ctx, SimpleNamespace(goals=None))
    assert ctx.goal_steps[real] == 7                                                     # the goal stays recorded
    assert not (tmp_path / "runs/checkpoints" / f"{real}.state").exists()                # its checkpoint is refused
    assert real in json.loads((tmp_path / "runs/milestones.json").read_text())           # the milestone still lands
    assert json.loads((run.parent / dc.LOG_NAME).read_text().splitlines()[0])["kind"] == "checkpoint_refused"


def test_record_goals_writes_the_checkpoint_when_clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    unverified = [g for g in GOALS if campaign.is_unverified(g)]
    real = next(g for g in GOALS if not campaign.is_unverified(g) and GOALS.index(g) > GOALS.index(unverified[0]))
    state = {g: False for g in GOALS}
    state[real] = True
    monkeypatch.setattr(press_goals, "check_goals", lambda e, c: dict(state))
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text("{}")
    ctx = SimpleNamespace(emu=FakeEmulator({0xD719: 5}), run_dir=run, step=7, frame=70, goal_steps={},
                          initial_goals=set(), initial_goals_ready=True, goal_left_house=False,
                          log=lambda m, t=None: None,
                          opts=SimpleNamespace(state_stem="", stop_at_goal=None, stop_at_map=None,
                                               headless=False, starter="x"))
    press_goals.record_goals(ctx, SimpleNamespace(goals=None))
    assert (tmp_path / "runs/checkpoints" / f"{real}.state").exists()
    assert not (run.parent / dc.LOG_NAME).exists()                                       # nothing refused


def _end_ctx(emu, tmp_path):
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    c = SimpleNamespace(emu=emu, run_dir=run, logs=[], initial_goals=set(),
                        opts=SimpleNamespace(state_path=""))
    c.log = lambda t, tag=None: c.logs.append(t)
    return c


def test_save_end_state_skips_the_write_while_active_and_writes_when_clean(tmp_path):
    ctx = _end_ctx(FakeEmulator({VFS: 6}), tmp_path)
    press_stop.save_end_state(ctx)
    assert not (ctx.run_dir / "end.state").exists()
    ctx.emu = FakeEmulator({})
    press_stop.save_end_state(ctx)
    assert (ctx.run_dir / "end.state").exists()


# --- fingerprint --------------------------------------------------------------------------------------------
def test_fingerprint_carries_the_signal_bytes_and_reasons_only_when_active():
    fp = statefp.fingerprint(FakeEmulator({0xD730: 0x12, 0xD358: 3, VFS: 1}))
    assert fp["text_flags"] == [0x12, 3] and fp["script_bytes"] == {"0xD618": 1}
    assert "glitch_active" not in fp
    fp = statefp.fingerprint(FakeEmulator({VFS: 6}))
    assert fp["glitch_active"] == ["script_oor"]
