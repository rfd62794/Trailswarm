"""The return-and-explore driver (goexplore/runner.py): fake run callable + tmp_path only, no emulator."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pokeagent import statefp
from pokeagent.goexplore import runner, store
from pokeagent.goexplore.archive import Archive, Entry

CID = "12.2.1.7.5.3.2"


def make_archive(root, cids=(CID,), goals=0, steps=100):
    """Save an Archive whose entries all point at real (dummy-bytes) cells/<cid>.state files."""
    a = Archive()
    for cid in cids:
        a.offer(Entry(cid, f"cells/{cid}.state", goals, steps))
        state = root / "cells" / f"{cid}.state"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_bytes(b"state")
    store.save(a, root)
    return a


def start_state(tmp_path):
    p = tmp_path / "start.state"
    p.write_bytes(b"state")
    return p


def fake_run(codes=(0,), calls=None):
    """A run callable recording (argv, cwd) and answering returncodes from ``codes`` (then 0)."""
    calls = calls if calls is not None else []
    it = iter(codes)

    def run(argv, cwd=None):
        calls.append((list(argv), cwd))
        return SimpleNamespace(returncode=next(it, 0))

    return run, calls


def test_empty_archive_starts_from_the_start_state(tmp_path):
    root, start = tmp_path / "arch", start_state(tmp_path)
    r = runner.pick(root, start, index=0, base_seed=7)
    assert r.cid is None and r.state == start and r.steps_offset == 0 and r.seed == 7
    argv = runner.command(r, root)
    assert "--cell-from" not in argv and "--cell-steps" not in argv
    assert not (root / "archive.json").exists()      # nothing to mark: pick writes no archive here


def test_pick_is_deterministic_and_returns_an_archived_cell(tmp_path):
    root = tmp_path / "arch"
    a = make_archive(root, cids=(CID, "3.4.5.1.0.1.0"), steps=111)
    r1 = runner.pick(root, start_state(tmp_path), index=2, base_seed=10, commit=False)
    r2 = runner.pick(root, start_state(tmp_path), index=2, base_seed=10, commit=False)
    assert r1.cid == r2.cid and r1.cid in a.entries
    assert r1.state == root / "cells" / f"{r1.cid}.state" and r1.state.is_file()
    assert r1.steps_offset == a.entries[r1.cid].steps == 111
    assert r1.seed == 12


def test_command_carries_parent_and_offset(tmp_path):
    r = runner.Return(index=1, cid=CID, state=tmp_path / "cells" / f"{CID}.state",
                      steps_offset=42, seed=13)
    argv = runner.command(r, tmp_path)
    val = lambda flag: argv[argv.index(flag) + 1]
    assert argv[1] == "tools/explore_demo.py" and "--headless" in argv
    assert val("--cell-dump") == str(tmp_path) and val("--state") == str(r.state)
    assert val("--cell-from") == CID and val("--cell-steps") == "42"
    assert val("--steps") == str(runner.DEFAULT_STEPS) == "600" and val("--seed") == "13"
    assert "--stop-at-goal" not in argv
    argv2 = runner.command(r, tmp_path, steps=50, stop_goal="beat_misty")
    assert argv2[argv2.index("--stop-at-goal") + 1] == "beat_misty"
    assert argv2[argv2.index("--steps") + 1] == "50"
    assert all(isinstance(x, str) for x in argv + argv2)


def test_mark_seen_is_saved_before_the_run_starts(tmp_path):
    root = tmp_path / "arch"
    make_archive(root)
    seen = {}

    def run(argv, cwd=None):
        d = json.loads((root / "archive.json").read_text(encoding="utf-8"))
        seen.update({cid: e["n_seen"] for cid, e in d["entries"].items()})
        return SimpleNamespace(returncode=0)

    assert runner.drive(root, start_state(tmp_path), returns=1, run=run) == [0]
    assert seen == {CID: 1}


def test_driver_does_not_write_the_archive_after_a_run(tmp_path):
    root = tmp_path / "arch"
    make_archive(root)

    def run(argv, cwd=None):
        b = store.load(root)                       # what a Harvester would add mid-run
        b.offer(Entry("9.9.9.9.9.9.9", "cells/9.9.9.9.9.9.9.state", 0, 5))
        store.save(b, root)
        return SimpleNamespace(returncode=0)

    assert runner.drive(root, start_state(tmp_path), returns=1, run=run) == [0]
    assert "9.9.9.9.9.9.9" in store.load(root).entries   # a stale driver save would have erased it


def test_synthetic_state_is_refused(tmp_path):
    root = tmp_path / "arch"
    make_archive(root)
    statefp.write(root / "cells" / f"{CID}.state", {"v": 1, "lineage": "synthetic"})
    run, calls = fake_run()
    with pytest.raises(ValueError):
        runner.drive(root, start_state(tmp_path), returns=1, run=run)
    assert calls == []

    synth = tmp_path / "synth.state"               # same refusal on the start state (empty archive)
    synth.write_bytes(b"state")
    statefp.write(synth, {"v": 1, "lineage": "synthetic"})
    with pytest.raises(ValueError):
        runner.pick(tmp_path / "empty-arch", synth, index=0, base_seed=0)


def test_missing_state_file_is_refused(tmp_path):
    root = tmp_path / "arch"
    a = Archive()
    a.offer(Entry(CID, f"cells/{CID}.state", 0, 100))   # entry but no cells/<cid>.state file
    store.save(a, root)
    run, calls = fake_run()
    with pytest.raises(FileNotFoundError):
        runner.drive(root, start_state(tmp_path), returns=1, run=run)
    assert calls == []


def test_nonzero_exit_stops_the_loop(tmp_path):
    root = tmp_path / "arch"
    make_archive(root)
    run, calls = fake_run(codes=[0, 1])
    assert runner.drive(root, start_state(tmp_path), returns=5, run=run) == [0, 1]
    assert len(calls) == 2


def test_second_driver_is_refused_and_lock_is_removed(tmp_path):
    root = tmp_path / "arch"
    make_archive(root)
    lock = root / "driver.lock"
    lock.write_text("held")
    run, calls = fake_run()
    with pytest.raises(RuntimeError):
        runner.drive(root, start_state(tmp_path), returns=1, run=run)
    assert lock.exists() and calls == []           # a live lock is not stolen

    lock.unlink()
    assert runner.drive(root, start_state(tmp_path), returns=1, run=run) == [0]
    assert not lock.exists()

    def boom(argv, cwd=None):
        raise OSError("spawn failed")
    with pytest.raises(OSError):
        runner.drive(root, start_state(tmp_path), returns=1, run=boom)
    assert not lock.exists()                       # released even when a run raises


def test_dry_run_changes_nothing(tmp_path):
    root = tmp_path / "arch"
    make_archive(root)
    before = (root / "archive.json").read_bytes()
    r = runner.pick(root, start_state(tmp_path), index=0, base_seed=0, commit=False)
    assert r.cid == CID
    assert (root / "archive.json").read_bytes() == before
    assert store.load(root).entries[CID].n_seen == 0


def test_corrupt_archive_stops_the_driver(tmp_path):
    root = tmp_path / "arch"
    root.mkdir()
    (root / "archive.json").write_text("not json{", encoding="utf-8")
    run, calls = fake_run()
    with pytest.raises(ValueError):
        runner.drive(root, start_state(tmp_path), returns=1, run=run)
    assert calls == [] and not (root / "driver.lock").exists()
