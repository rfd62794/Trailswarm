import json
import os
from pathlib import Path

import numpy as np

from pokeagent.mapview.ghosts import GhostStore, load_ghost


def doc(**kw):
    d = {"schema": 1, "game": "g", "run": "r1", "agent": "w-1", "outcome": "death",
         "every": 2, "points": [["a-1", 12, 88], ["a-1", 14, 80], ["b-1", 3, 40]]}
    d.update(kw)
    return d


def write(tmp_path: Path, name: str, d) -> Path:
    p = tmp_path / "ghosts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_load_ghost_valid(tmp_path):
    g = load_ghost(write(tmp_path, "r1.json", doc()), ["a-1", "b-1"])
    assert (g.run, g.agent, g.outcome, g.every) == ("r1", "w-1", "death", 2)
    assert g.area_idx.dtype == np.int16 and list(g.area_idx) == [0, 0, 1]
    assert g.xs.dtype == np.float32 and g.ys.dtype == np.float32
    assert list(g.xs) == [12, 14, 3] and list(g.ys) == [88, 80, 40]


def test_load_ghost_unknown_area_marks_minus_one(tmp_path):
    p = write(tmp_path, "r1.json", doc())
    assert list(load_ghost(p, ["b-1"]).area_idx) == [-1, -1, 0]
    assert list(load_ghost(p).area_idx) == [0, 0, 1]                # no order: first-appearance


def test_load_ghost_returns_none_never_raises(tmp_path):
    gdir = tmp_path / "ghosts"
    gdir.mkdir()
    (gdir / "truncated.json").write_text('{"schema": 1, "run"')
    cases = [gdir / "truncated.json",
             write(tmp_path, "schema2.json", doc(schema=2)),
             write(tmp_path, "no-points.json", {k: v for k, v in doc().items() if k != "points"}),
             write(tmp_path, "no-run.json", {k: v for k, v in doc().items() if k != "run"}),
             write(tmp_path, "every0.json", doc(every=0)),
             write(tmp_path, "every-str.json", doc(every="2")),
             write(tmp_path, "empty.json", doc(points=[])),
             write(tmp_path, "short-point.json", doc(points=[["a-1", 1]])),
             write(tmp_path, "bad-x.json", doc(points=[["a-1", "x", 5]])),
             write(tmp_path, "bad-area.json", doc(points=[[5, 1, 2]]))]
    for p in cases:
        assert load_ghost(p) is None, p.name
    assert load_ghost(gdir / "missing.json") is None


def test_store_refresh_picks_up_new_drops_gone_reparses_changed(tmp_path):
    write(tmp_path, "r1.json", doc(run="r1"))
    write(tmp_path, "r2.json", doc(run="r2", agent="w-2"))
    store = GhostStore()
    store.set_area_names(["a-1", "b-1"])
    assert store.refresh(tmp_path) is True and len(store.ghosts) == 2 and store.parsed == 2
    assert store.refresh(tmp_path) is False and store.parsed == 2   # cached: no re-parse
    write(tmp_path, "r3.json", doc(run="r3"))
    assert store.refresh(tmp_path) is True and len(store.ghosts) == 3 and store.parsed == 3
    p = write(tmp_path, "r1.json", doc(run="r1", outcome="best"))
    os.utime(p, (1_800_000_000, 1_800_000_000))
    assert store.refresh(tmp_path) is True and store.parsed == 4    # only the changed file
    (tmp_path / "ghosts" / "r2.json").unlink()
    assert store.refresh(tmp_path) is True
    assert [g.run for g in store.ghosts] == ["r1", "r3"]            # the deleted one is forgotten


def test_store_reindexes_when_the_area_order_grows(tmp_path):
    write(tmp_path, "r1.json", doc(points=[["a-1", 1, 1], ["b-1", 2, 2]]))
    store = GhostStore()
    store.set_area_names(["a-1"])
    store.refresh(tmp_path)
    assert list(store.ghosts[0].area_idx) == [0, -1]                # b-1 not captured yet
    assert store.set_area_names(["a-1", "b-1"]) is True
    assert list(store.ghosts[0].area_idx) == [0, 1]                 # appears without re-parsing
    assert store.parsed == 1


def test_non_finite_coordinates_reject_the_ghost(tmp_path):
    for bad in (float("nan"), float("inf")):
        p = write(tmp_path, "n.json", doc(points=[["a-1", bad, 3]]))
        assert load_ghost(p, ["a-1"]) is None


def test_permanently_bad_file_is_parsed_once(tmp_path):
    write(tmp_path, "ok.json", doc())
    (tmp_path / "ghosts" / "bad.json").write_text("{nope", encoding="utf-8")
    store = GhostStore()
    store.refresh(tmp_path)
    n = store.parsed
    assert store.refresh(tmp_path) is False and store.parsed == n
    (tmp_path / "ghosts" / "bad.json").write_text("{nope still", encoding="utf-8")
    store.refresh(tmp_path)
    assert store.parsed == n + 1
