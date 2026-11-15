"""semantic_view + Dataset.semantic: one shared class table, or the documented refusal."""
from __future__ import annotations

import json

import numpy as np
import pytest

from pokeagent.vision.store import Store
from pokeagent.vision_model import data, semantic_view
from pokeagent.vision_model.semantic import SEMANTIC


def _ds(sem):
    n = 3
    return data.Dataset(
        images=np.zeros((n, 16, 16, 3), np.uint8),
        label=np.array([7, 13, 44], np.int32),
        coarse=np.array([4, 1, 4], np.int8),
        area=np.array(["a", "b", "c"]),
        kind=np.array([1, 0, 1], np.int8),
        bank=np.array([2, -1, 2], np.int32),
        weight=np.ones(n, np.float32),
        w=np.full(n, 8, np.int32), h=np.full(n, 8, np.int32),
        ids=np.array(["x", "y", "z"]),
        semantic=None if sem is None else np.array(sem, np.int8))


def test_as_semantic_raises_without_labels():
    with pytest.raises(ValueError, match="no semantic labels"):
        semantic_view.as_semantic(_ds(None))


def test_as_semantic_shares_one_class_table():
    ds = _ds([SEMANTIC.index(c) for c in ("walkable", "item", "solid")])
    view = semantic_view.as_semantic(ds)
    assert view.label.tolist() == [0, 6, 1] and view.label.dtype == np.int32
    assert (view.kind == 0).all() and (view.bank == -1).all()
    assert (view.ids == ds.ids).all() and (view.area == ds.area).all()
    assert (view.coarse == ds.coarse).all() and (view.weight == ds.weight).all()
    keys = {data.row_key(view, i) for i in range(len(view.label))}
    assert keys == {("sprite", -1, 0), ("sprite", -1, 1), ("sprite", -1, 6)}
    assert semantic_view.class_name(("sprite", -1, 6)) == "item"
    assert semantic_view.class_name(("sprite", -1, 8)) == "other"


def test_select_carries_semantic():
    ds = _ds([0, 5, 1])
    sub = ds.select(np.array([0, 2]))
    assert sub.semantic.tolist() == [0, 1]
    assert _ds(None).select(np.array([0])).semantic is None


def test_load_dataset_fills_semantic_only_when_every_row_has_it(tmp_path):
    store = Store(tmp_path)
    store.add_crop("tile", 7, "terrain", "m", "r0c0", 0, 0, 8, 8, 2,
                   np.full((8, 8, 3), 7, np.uint8))
    store.add_crop("sprite", 13, "npc", "m", "r1c1", 0, 0, 16, 16, None,
                   np.full((16, 16, 3), 9, np.uint8))
    store.flush()
    assert data.load_dataset(tmp_path).semantic is None      # unlabelled rows
    path = tmp_path / "samples.jsonl"
    rows = [json.loads(ln) for ln in path.read_text().splitlines()]
    rows.sort(key=lambda r: r["kind"], reverse=True)         # tile row first
    rows[0]["semantic"] = "walkable"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert data.load_dataset(tmp_path).semantic is None      # one row unlabelled
    rows[1]["semantic"] = "npc"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    ds = data.load_dataset(tmp_path)
    assert sorted(ds.semantic.tolist()) == [SEMANTIC.index("walkable"),
                                            SEMANTIC.index("npc")]
    rows[1]["semantic"] = "bogus"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert data.load_dataset(tmp_path).semantic is None      # a bad value poisons all
