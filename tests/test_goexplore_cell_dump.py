"""The mid-run cell harvest (goexplore/cell_dump.py): FakeEmulator + tmp_path only."""
from __future__ import annotations

import pytest

from pokeagent import statefp
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.goals import GOALS
from pokeagent.goexplore import cell_dump, store
from pokeagent.goexplore.archive import Entry
from pokeagent.goexplore.cell import cell_id, from_snapshot
from pokeagent.novelty.features import read_snapshot

MAP, PX, PY, FLAGS, PARTY_N = 0xD35E, 0xD362, 0xD361, 0xD747, 0xD163
MON1 = 0xD16B          # wPartyMon1 (44-byte party_struct: hp +1, level +33, max_hp +34)


def make_ctx(tmp_path, mem=None, state_path=""):
    emu = FakeEmulator({MAP: 12, PX: 9, PY: 5, **(mem or {})})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"),
                          opts=ExplorerOptions(state_path=state_path), run_dir=tmp_path / "run")
    ctx.goals = lambda: {}     # goal_stage -> GOALS[0] -> goals_reached 0; tests override per case
    return ctx


def mon(level=5, species=25):
    """RAM bytes for a one-mon party at ``level`` (hp 30/30)."""
    return {PARTY_N: 1, MON1: species, MON1 + 2: 30, MON1 + 33: level, MON1 + 35: 30}


class StubEngine:
    """The tiny engine the directive allows: step() bumps ctx.step and returns a sentinel."""

    def __init__(self, ctx):
        self.ctx = ctx

    def step(self):
        self.ctx.step += 1
        return "sentinel"


def states(root):
    return sorted((root / "cells").glob("*.state"))


def test_first_tick_saves_state_sidecar_and_archive(tmp_path):
    ctx = make_ctx(tmp_path, mem=mon(5))
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    cid = h.tick()
    assert cid == cell_id(from_snapshot(read_snapshot(ctx.emu), 0))
    state = tmp_path / "arch" / "cells" / f"{cid}.state"
    assert state.exists() and statefp.read(state) is not None
    arch = store.load(tmp_path / "arch")
    assert arch.entries[cid].state == f"cells/{cid}.state"
    assert arch.entries[cid].goals == 0 and arch.entries[cid].steps == ctx.step
    assert arch.entries[cid].lineage == "organic"
    assert (tmp_path / "arch" / "archive.json").exists()


def test_flag_bucket_splits_cells(tmp_path):
    ctx = make_ctx(tmp_path)
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    c1 = h.tick()
    ctx.step += cell_dump.CHECK_EVERY
    ctx.emu.set(FLAGS, 0b1)                    # one extra bit: same //4 bucket, same cell
    assert h.tick() is None and len(states(tmp_path / "arch")) == 1
    ctx.step += cell_dump.CHECK_EVERY
    for i in range(1, 5):                      # four more bits: flag_popcount 5 -> flag4 1, a NEW cell
        ctx.emu.set(FLAGS + i, 0b1)
    c2 = h.tick()
    assert c2 is not None and c2 != c1
    assert (tmp_path / "arch" / "cells" / f"{c2}.state").exists()
    assert len(states(tmp_path / "arch")) == 2


def test_party_level_bucket_splits_cells(tmp_path):
    ctx = make_ctx(tmp_path, mem=mon(4))
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    c1 = h.tick()
    ctx.step += cell_dump.CHECK_EVERY
    ctx.emu.set(MON1 + 33, 5)                  # max level 4 -> 5 crosses the //5 bucket
    c2 = h.tick()
    assert c2 is not None and c2 != c1
    assert (tmp_path / "arch" / "cells" / f"{c2}.state").exists()


def test_checks_run_every_check_every_and_unchanged_cells_are_not_resaved(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    reads, saves = [], []
    real_read, real_save = cell_dump.read_snapshot, ctx.emu.save_state
    monkeypatch.setattr(cell_dump, "read_snapshot", lambda e: (reads.append(1), real_read(e))[1])
    monkeypatch.setattr(ctx.emu, "save_state", lambda p: (saves.append(p), real_save(p))[1])
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    h.tick()                                   # step 0: the first check always runs and saves
    assert reads == [1] and len(saves) == 1
    for _ in range(cell_dump.CHECK_EVERY - 1): # steps 1..9: no check at all
        ctx.step += 1
        h.tick()
    assert reads == [1] and len(saves) == 1
    ctx.step += 1                              # step 10: a check runs, but the same cell scores worse
    assert h.tick() is None
    assert reads == [1, 1] and len(saves) == 1


def test_higher_goals_count_at_the_same_position_replaces_and_keeps_n_seen(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.goals = lambda: {g: True for g in GOALS[:2]}   # goal_stage -> GOALS[2] -> goals_reached 2
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    cid = cell_id(from_snapshot(read_snapshot(ctx.emu), 2))
    h.archive.offer(Entry(cid, f"cells/{cid}.state", 0, 9999, n_seen=3))  # a stale, worse twin of this cell
    assert h.tick() == cid                       # (2, -steps) beats (0, -9999): replace, keep n_seen
    e = h.archive.entries[cid]
    assert e.goals == 2 and e.steps == ctx.step and e.n_seen == 3
    assert (tmp_path / "arch" / "cells" / f"{cid}.state").exists()


def test_attach_wrapper_returns_exactly_the_original_step_result(tmp_path):
    ctx = make_ctx(tmp_path)
    engine = StubEngine(ctx)
    h = cell_dump.attach(ctx, engine, tmp_path / "arch")
    assert isinstance(h, cell_dump.Harvester)
    assert engine.step() == "sentinel" and ctx.step == 1


def test_failing_save_is_swallowed(tmp_path):
    ctx = make_ctx(tmp_path)
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    def boom(path):
        raise OSError("disk full")
    ctx.emu.save_state = boom
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    assert h.tick() is None
    assert "cell dump skipped" in logs[0]


def test_synthetic_start_refused(tmp_path):
    state = tmp_path / "start.state"
    state.write_text("{}")
    statefp.write(state, {"v": 1, "lineage": "synthetic"})
    ctx = make_ctx(tmp_path, state_path=str(state))
    with pytest.raises(ValueError):
        cell_dump.attach(ctx, StubEngine(ctx), tmp_path / "arch")

    organic = tmp_path / "organic.state"         # no sidecar reads "organic": accepted
    organic.write_text("{}")
    ctx2 = make_ctx(tmp_path, state_path=str(organic))
    assert isinstance(cell_dump.attach(ctx2, StubEngine(ctx2), tmp_path / "arch"), cell_dump.Harvester)
    ctx3 = make_ctx(tmp_path)                    # empty state_path: the check is skipped
    assert isinstance(cell_dump.attach(ctx3, StubEngine(ctx3), tmp_path / "arch"), cell_dump.Harvester)


def test_parent_chain_links_consecutive_cells(tmp_path):
    ctx = make_ctx(tmp_path)
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    a = h.tick()
    ctx.step += cell_dump.CHECK_EVERY
    ctx.emu.set(PX, 20)                          # x 9 -> 20: a different 4x4 block, a different cell
    b = h.tick()
    assert b is not None and b != a
    assert h.archive.entries[b].parent == a
    assert h.archive.entries[a].parent is None   # the first cell of a run has no previous cell


def test_a_better_revisit_keeps_its_parent_so_the_chain_has_no_cycle(tmp_path):
    ctx = make_ctx(tmp_path)
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    a = h.tick()                                 # A first
    ctx.step += cell_dump.CHECK_EVERY
    ctx.emu.set(PX, 20)
    b = h.tick()                                 # B, parent A
    ctx.step += cell_dump.CHECK_EVERY
    ctx.emu.set(PX, 9)
    h.steps_offset = -10 * cell_dump.CHECK_EVERY  # e.g. a later run that reached A sooner
    assert h.tick() == a                         # A again from B in fewer steps: replaced
    assert h.archive.entries[b].parent == a
    assert h.archive.entries[a].parent is None   # kept, not B: no A<->B cycle


def test_a_new_cell_is_never_its_own_parent(tmp_path):
    ctx = make_ctx(tmp_path)
    h = cell_dump.Harvester(ctx, tmp_path / "arch", parent=None)
    h.prev = "gone"                              # the previous cell was evicted: not archived
    assert h._parent_for("x") is None
    h.parent = "x"
    assert h._parent_for("x") is None            # never itself


def test_every_written_entry_state_survives_load(tmp_path):
    ctx = make_ctx(tmp_path)
    h = cell_dump.Harvester(ctx, tmp_path / "arch")
    h.tick()
    ctx.step += cell_dump.CHECK_EVERY
    ctx.emu.set(PX, 20)
    h.tick()
    arch = store.load(tmp_path / "arch")         # load rejects paths outside cells/ or with a backslash
    assert len(arch.entries) == 2
    assert all(e.state.startswith("cells/") and "\\" not in e.state for e in arch.entries.values())
