"""The on-disk store: atomic archive.json, add_state + stamped sidecar, weighted leaf eviction."""
from __future__ import annotations

import json

import pytest

from pokeagent import checkpoint_goals, statefp
from pokeagent.emulator import FakeEmulator
from pokeagent.goexplore import store
from pokeagent.goexplore.archive import Archive, Entry


def ent(cid, goals=0, steps=100, n_seen=0, parent=None):
    return Entry(cid=cid, state=f"cells/{cid}.state", goals=goals, steps=steps,
                 n_seen=n_seen, parent=parent)


def emu():
    return FakeEmulator({0xD35E: 12, 0xD362: 9, 0xD361: 5})


def test_save_load_round_trip(tmp_path):
    a = Archive(cap=7)
    a.offer(ent("b", goals=1, steps=5))
    a.offer(ent("a", goals=0, steps=9, n_seen=2, parent="b"))
    store.save(a, tmp_path)
    text = (tmp_path / "archive.json").read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True)
    assert json.loads(text)["v"] == 1
    b = store.load(tmp_path)
    assert b.cap == 7 and b.entries == a.entries


def test_atomic_write_never_leaves_a_half_file(tmp_path, monkeypatch):
    a = Archive()
    a.offer(ent("c", goals=1))
    store.save(a, tmp_path)
    first = (tmp_path / "archive.json").read_text(encoding="utf-8")

    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", boom)
    a.entries["c"] = ent("c", goals=2, steps=1)
    with pytest.raises(OSError):
        store.save(a, tmp_path)
    assert (tmp_path / "archive.json").read_text(encoding="utf-8") == first
    json.loads(first)
    assert not list(tmp_path.glob("*.tmp"))


def test_no_tmp_left_after_success(tmp_path):
    a = Archive()
    a.offer(ent("c"))
    store.save(a, tmp_path / "sub")
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["archive.json"]


def test_load_missing_is_empty_and_corrupt_raises(tmp_path):
    assert len(store.load(tmp_path / "nope")) == 0
    (tmp_path / "archive.json").write_text("not json{", encoding="utf-8")
    with pytest.raises(ValueError):
        store.load(tmp_path)
    (tmp_path / "archive.json").write_text('{"v": 99, "cap": 3, "entries": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        store.load(tmp_path)


def test_add_state_writes_state_and_stamped_sidecar(tmp_path):
    e = emu()
    rel = store.add_state(e, tmp_path, "12.2.1.0.-.-.-", "r1")
    assert rel == "cells/12.2.1.0.-.-.-.state"
    state = tmp_path / rel
    assert state.exists()
    fp = statefp.read(state)
    assert fp["map"] == 12 and fp["x"] == 9 and fp["y"] == 5 and fp["source_run"] == "r1"
    assert statefp.lineage(state) == "organic"
    assert not list((tmp_path / "cells").glob("*.tmp"))


def test_evict_drops_lowest_weight_leaf(tmp_path):
    e = emu()
    a = Archive(cap=3)
    for cid, g, s, n in (("c0", 0, 10, 0), ("c1", 0, 20, 99), ("c2", 0, 30, 8),
                         ("c3", 0, 40, 0), ("c4", 1, 5, 0)):
        store.add_state(e, tmp_path, cid)
        a.offer(ent(cid, goals=g, steps=s, n_seen=n))
        checkpoint_goals.sidecar(tmp_path / "cells" / f"{cid}.state").write_text('{"completed": []}')
    assert store.evict(a, tmp_path) == ["c1", "c2"]      # c0/c4 best-per-goals; c3 the heavy survivor
    for cid in ("c1", "c2"):
        for p in (tmp_path / "cells" / f"{cid}.state",
                  statefp.sidecar(tmp_path / "cells" / f"{cid}.state"),
                  checkpoint_goals.sidecar(tmp_path / "cells" / f"{cid}.state")):
            assert not p.exists()
    for cid in ("c0", "c3", "c4"):
        assert (tmp_path / "cells" / f"{cid}.state").exists()


def test_evict_never_drops_best_per_goals(tmp_path):
    e = emu()
    a = Archive(cap=2)
    for cid, kw in (("low", dict(goals=1, steps=999, n_seen=999)),
                    ("mid", dict(goals=0, steps=5)),
                    ("high", dict(goals=0, steps=50))):
        store.add_state(e, tmp_path, cid)
        a.offer(ent(cid, **kw))
    assert store.evict(a, tmp_path) == ["high"]          # low survives: best of its goals count
    assert set(a.entries) == {"low", "mid"}

    b = Archive(cap=1)                                   # everyone best-per-goals: nothing to drop
    b.offer(ent("g0", goals=0))
    b.offer(ent("g1", goals=1))
    assert store.evict(b, tmp_path) == [] and len(b) == 2

    c = Archive(cap=1)                                   # the only candidate is protected: stays over cap
    c.offer(ent("p0", goals=0, steps=1))
    c.offer(ent("p1", goals=0, steps=9))
    assert store.evict(c, tmp_path, protected=frozenset({"p1"})) == [] and len(c) == 2


def test_evict_never_drops_protected_or_cells_with_children(tmp_path):
    e = emu()
    a = Archive(cap=2)
    store.add_state(e, tmp_path, "best")
    store.add_state(e, tmp_path, "mom")
    store.add_state(e, tmp_path, "kid")
    a.offer(ent("best", goals=0, steps=1))
    a.offer(ent("mom", goals=0, steps=50, n_seen=399))   # lowest weight but has a live child
    a.offer(ent("kid", goals=0, steps=99, n_seen=99, parent="mom"))
    assert store.evict(a, tmp_path) == ["kid"]
    assert "mom" in a.entries

    b = Archive(cap=1)                                   # mom becomes a leaf once kid is gone
    b.offer(ent("best", goals=0, steps=1))
    b.offer(ent("mom", goals=0, steps=50))
    b.offer(ent("kid", goals=0, steps=99, parent="mom"))
    assert store.evict(b, tmp_path) == ["kid", "mom"]


def test_evict_is_deterministic(tmp_path):
    def build(root):
        e = emu()
        a = Archive(cap=2)
        for i, n in enumerate((0, 99, 99, 0)):           # a weight tie: broken by the smaller cid
            cid = f"1.0.{i}.0.-.-.-"
            store.add_state(e, root, cid)
            a.offer(ent(cid, goals=0, steps=100 + i, n_seen=n))
        return a
    r1, r2 = tmp_path / "r1", tmp_path / "r2"
    gone = store.evict(build(r1), r1)
    assert gone == ["1.0.1.0.-.-.-", "1.0.2.0.-.-.-"]
    assert store.evict(build(r2), r2) == gone


@pytest.mark.parametrize("bad", ["../escape.state", "cells/../../escape.state", "/abs/x.state", "C:/x.state", "other/x.state", "cells/..\\..\\x.state"])
def test_load_rejects_state_paths_outside_cells(tmp_path, bad):
    a = Archive()
    a.offer(Entry(cid="x", state=bad, goals=0, steps=1))
    store.save(a, tmp_path)
    with pytest.raises(ValueError):
        store.load(tmp_path)
