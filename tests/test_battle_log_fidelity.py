"""Battle log fidelity (2026-11-07 directive): outcome on every record, battle_map vs end_map, stage/trainer,
party_before/party_after on every record (party_error on failure), a fingerprint beside every new goal checkpoint,
and 0xD719 wLastBlackoutMap verified in both RAM data files."""
from __future__ import annotations

import json
from importlib import resources
from types import SimpleNamespace

from pokeagent import campaign, ram_lookup, statefp
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import party_log, press_goals
from pokeagent.explorer.grind import outcome_of
from pokeagent.goals import GOALS
from test_xp_logging import make_ctx as xp_ctx, party


# ---- 1. outcome_of: one word for how the battle ended ----
def test_outcome_of_labels():
    assert outcome_of(trainer=False, won=True, moved_away=False, party_count=1) == "won"
    assert outcome_of(trainer=True, won=False, moved_away=True, party_count=1) == "blackout"   # loss that warped us
    assert outcome_of(trainer=False, won=False, moved_away=False, party_count=2) == "fled"     # wild, alive, not won
    assert outcome_of(trainer=True, won=False, moved_away=False, party_count=2) == "lost"      # trainer, alive, no warp
    assert outcome_of(trainer=False, won=False, moved_away=False, party_count=0) == "blackout"  # no party standing


# ---- 2. PartyLog.end_battle: party on every record, blackouts counted right, never raises ----
def test_end_battle_blackout_counts_and_returns_both_snapshots(tmp_path):
    ctx = xp_ctx(tmp_path, party((153, 5, 135, 20, 20)))
    log = party_log.of(ctx)
    log.start_battle(ctx)
    fields = log.end_battle(ctx, won=False, fled=False)  # a blackout: lost and not a flee
    assert log.blackouts == 1
    assert fields["party_before"] == [[153, 5, 135, 20, 20]] and fields["party_after"] == [[153, 5, 135, 20, 20]]


def test_end_battle_after_read_failure_keeps_before_and_marks_error(tmp_path, monkeypatch):
    ctx = xp_ctx(tmp_path, party((153, 5, 135, 20, 20)))
    log = party_log.of(ctx)
    log.start_battle(ctx)
    monkeypatch.setattr(party_log, "snapshot", lambda emu: (_ for _ in ()).throw(OSError("ram gone")))
    fields = log.end_battle(ctx, won=True, fled=False)
    assert fields["party_before"] == [[153, 5, 135, 20, 20]] and "party_after" not in fields
    assert "party_error" in fields and "ram gone" in fields["party_error"]


def test_end_battle_never_raises_even_with_no_before_and_a_dead_after(tmp_path, monkeypatch):
    ctx = xp_ctx(tmp_path, {})
    log = party_log.of(ctx)  # no start_battle: self.before is None
    monkeypatch.setattr(party_log, "snapshot", lambda emu: (_ for _ in ()).throw(OSError("ram gone")))
    fields = log.end_battle(ctx, won=False, fled=True)
    assert "party_error" in fields and "party_before" not in fields and "party_after" not in fields


# ---- 3. the battle-end record block (build_record) and the full step() path ----
def test_build_record_blackout_and_win():
    from pokeagent.explorer.behaviours.battle import build_record

    bl = {"start": 3, "kind": 1, "turns": []}
    build_record(bl, step=15, run="explore-1", won=False, hp_end=[79, 79], outcome="blackout",
                 battle_map=0x61, end_map=3, stage="rival_ss_anne", trainer={"map": 0x61, "x": 4, "y": 5, "pic": 7})
    assert bl["outcome"] == "blackout" and bl["fled"] is False and bl["won"] is False
    assert bl["map"] == bl["battle_map"] == 0x61 and bl["end_map"] == 3
    for k in ("end", "won", "run", "map", "presses", "hp_end", "fled", "outcome", "battle_map", "end_map", "stage", "trainer"):
        assert k in bl

    bl = {"start": 3}
    build_record(bl, step=15, run="r", won=True, hp_end=[10, 20], outcome="won",
                 battle_map=0x28, end_map=0x28, stage=None, trainer=None)
    assert bl["map"] == bl["end_map"] == 0x28 and bl["fled"] is False and bl["outcome"] == "won"


def test_battle_end_record_blackout_via_step(tmp_path, monkeypatch):
    """A trainer fight on the ship that ends with us warped to Cerulean: a blackout, mapped to the fight's map."""
    from pokeagent.explorer.behaviours import Battle

    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    mem = party((153, 5, 135, 20, 20))
    mem.update({0xD35E: 3, 0xD362: 8, 0xD361: 9, 0xD057: 0})  # after the warp: standing in Cerulean, party healed
    ctx = xp_ctx(tmp_path, mem)
    ctx.in_battle = True
    ctx.battle_pos = (0x61, 13, 6)  # the fight started on S.S. Anne map 0x61
    ctx.battle_log = {"start": 3, "kind": 2, "you": [0, 8], "enemy": [165, 3], "enemy_species": 165, "turns": []}
    ctx.trainer_npc = {"pic": 55, "slot": 3, "last": [10, 7], "trainer": True}
    ctx.step = 15
    party_log.of(ctx).before = party_log.snapshot(ctx.emu)
    ctx.refresh()
    Battle().step(ctx)
    rec = json.loads((tmp_path / "runs" / "battles.jsonl").read_text().splitlines()[-1])
    assert rec["outcome"] == "blackout" and rec["fled"] is False and rec["won"] is False
    assert rec["map"] == rec["battle_map"] == 0x61 and rec["end_map"] == 3
    assert rec["trainer"] == {"map": 0x61, "pic": 55, "x": 10, "y": 7}
    assert "stage" in rec
    assert party_log.of(ctx).blackouts == 1
    for k in ("start", "kind", "you", "enemy", "enemy_species", "end", "won", "run", "map", "presses", "hp_end",
              "fled", "turns", "party_before", "party_after"):
        assert k in rec


def test_battle_end_record_win_via_step(tmp_path, monkeypatch):
    from pokeagent.explorer.behaviours import Battle

    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    mem = party((153, 5, 135, 20, 20))
    mem.update({0xD35E: 0x28, 0xD362: 5, 0xD361: 6, 0xD057: 0})
    ctx = xp_ctx(tmp_path, mem)
    ctx.in_battle = True
    ctx.battle_pos = (0x28, 5, 6)
    ctx.battle_log = {"start": 3, "kind": 1, "you": [0, 8], "enemy": [165, 3], "enemy_species": 165, "turns": []}
    ctx.step = 15
    party_log.of(ctx).before = party_log.snapshot(ctx.emu)
    ctx.refresh()
    Battle().step(ctx)
    rec = json.loads((tmp_path / "runs" / "battles.jsonl").read_text().splitlines()[-1])
    assert rec["outcome"] == "won" and rec["fled"] is False
    assert rec["map"] == rec["battle_map"] == rec["end_map"] == 0x28 and rec["trainer"] is None


# ---- 4. press_goals: a fresh fingerprint beside every new checkpoint (inferred-goals test's setup, FakeEmulator) ----
def _goals_ctx(tmp_path, monkeypatch, emu):
    unverified = [g for g in GOALS if campaign.is_unverified(g)]
    real = next(g for g in GOALS if not campaign.is_unverified(g) and GOALS.index(g) > GOALS.index(unverified[0]))
    state = {g: False for g in GOALS}
    state[real] = True
    monkeypatch.setattr(press_goals, "check_goals", lambda e, c: dict(state))
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text("{}")
    ctx = SimpleNamespace(emu=emu, run_dir=run, step=7, frame=70, goal_steps={}, initial_goals=set(), initial_goals_ready=True,
                          goal_left_house=False, log=lambda m, t=None: None,
                          opts=SimpleNamespace(state_stem="", stop_at_goal=None, stop_at_map=None, headless=False, starter="x"))
    return real, ctx, SimpleNamespace(goals=None)


def test_new_checkpoint_gets_a_fresh_fingerprint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real, ctx, fr = _goals_ctx(tmp_path, monkeypatch, FakeEmulator({0xD719: 5}))
    press_goals.record_goals(ctx, fr)
    state = tmp_path / "runs/checkpoints" / f"{real}.state"
    assert state.exists()
    fp = statefp.read(state)
    assert fp is not None and fp["respawn"] == 5 and fp["source_run"] == "run"


def test_stamp_failure_still_leaves_the_state_and_milestone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(statefp, "stamp", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    real, ctx, fr = _goals_ctx(tmp_path, monkeypatch, FakeEmulator({0xD719: 5}))
    press_goals.record_goals(ctx, fr)
    state = tmp_path / "runs/checkpoints" / f"{real}.state"
    assert state.exists()
    assert real in json.loads((tmp_path / "runs/milestones.json").read_text())


# ---- 5. 0xD719 wLastBlackoutMap verified in both data files; ram_map.json still parses ----
def test_blackout_map_verified_in_both_data_files():
    text = resources.files("pokeagent.data").joinpath("ram_map.json").read_text(encoding="utf-8")
    assert isinstance(json.loads(text), list)
    e = next(x for x in ram_lookup.load_map() if x.name == "wLastBlackoutMap")
    assert e.verified is True and "229 save states" in e.evidence
    names = json.loads(resources.files("pokeagent.data").joinpath("ram_names.json").read_text(encoding="utf-8"))
    n = next(x for x in names if x["name"] == "wLastBlackoutMap")
    assert n["verified"] is True and "229 save states" in n["note"]
