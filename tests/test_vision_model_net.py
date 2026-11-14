"""With torch: TinyNet size, synthetic learnability, determinism, export guard.

Every torch test skips cleanly where torch is absent (the vision group is optional).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from pokeagent.vision_model import data, split


def synth(n_areas=6, per_class=3):
    """4 classes x 6 areas: one bright quadrant each, plus small noise."""
    rng = np.random.default_rng(7)
    base = np.zeros((4, 16, 16, 3), np.uint8)
    base[0, :8, :8] = 255
    base[1, 8:, :8] = 255
    base[2, :8, 8:] = 255
    base[3, 8:, 8:] = 255
    imgs, labels, coarse, areas, ids = [], [], [], [], []
    for a in range(n_areas):
        for cls in range(4):
            for r in range(per_class):
                noise = rng.integers(0, 40, base[cls].shape)
                imgs.append(np.clip(base[cls].astype(int) + noise, 0, 255)
                            .astype(np.uint8))
                labels.append(cls)
                coarse.append(cls % len(data.COARSE))
                areas.append(f"a{a}")
                ids.append(f"a{a}c{cls}r{r}")
    n = len(imgs)
    return data.Dataset(np.stack(imgs), np.array(labels, np.int32),
                        np.array(coarse, np.int8), np.array(areas),
                        np.zeros(n, np.int8), np.full(n, -1, np.int32),
                        np.ones(n, np.float32), np.full(n, 16, np.int32),
                        np.full(n, 16, np.int32), np.array(ids))


def test_param_count_under_30k():
    pytest.importorskip("torch")
    from pokeagent.vision_model import net
    assert net.param_count(net.TinyNet(200)) < 30000


def test_trains_synthetic_above_09_fast():
    pytest.importorskip("torch")
    from pokeagent.vision_model import net
    ds = synth()
    train_areas, test_areas = split.split_by_area(ds.area, seed=0)
    tr = split.area_indices(ds.area, train_areas)
    te = split.area_indices(ds.area, test_areas)
    table = data.class_table(ds.select(tr))
    t0 = time.process_time()  # CPU time: wall time failed under load (swarm + verifies, 2026-11-14)
    res = net.train(ds, tr, table, epochs=80, batch=16, seed=0, threads=1)
    lab, co = net.predict(res.model, ds.images[te])
    assert time.process_time() - t0 < 10
    assert (lab == data.encode(ds.select(te), table)).mean() > 0.9
    assert (co == ds.coarse[te].astype(np.int64)).mean() > 0.9


def test_same_seed_same_predictions():
    pytest.importorskip("torch")
    from pokeagent.vision_model import net
    ds = synth()
    tr = np.arange(len(ds.label))
    table = data.class_table(ds)
    r1 = net.train(ds, tr, table, epochs=4, batch=16, seed=3)
    r2 = net.train(ds, tr, table, epochs=4, batch=16, seed=3)
    l1, _ = net.predict(r1.model, ds.images)
    l2, _ = net.predict(r2.model, ds.images)
    assert (l1 == l2).all()


def test_export_refuses_outside_runs(tmp_path):
    pytest.importorskip("torch")
    from pokeagent.vision_model import export, net
    with pytest.raises(ValueError):
        export.save(net.TinyNet(2), {("sprite", -1, 1): 0}, tmp_path / "x")


def test_export_roundtrip(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    from pokeagent.vision_model import export, net
    monkeypatch.chdir(tmp_path)
    table = {("sprite", -1, 1): 0, ("tile", 2, 5): 1}
    model = net.TinyNet(len(table))
    export.save(model, table, Path("runs") / "vision_models" / "g")
    model2, table2 = export.load(Path("runs") / "vision_models" / "g")
    assert table2 == table
    imgs = np.zeros((2, 16, 16, 3), np.uint8)
    l1, _ = net.predict(model, imgs)
    l2, _ = net.predict(model2, imgs)
    assert (l1 == l2).all()
