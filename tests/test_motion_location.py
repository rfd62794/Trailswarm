"""location_*: thumbnail loading, the nearest-thumbnail baseline, the optional CNN."""
from __future__ import annotations

import time

import numpy as np
import pytest

from pokeagent.vision_motion import (location_baseline, location_data, report,
                                   split)


def _thumbs():
    """Synthetic thumbnails: area = base tone, cell = stripe code. Distinct per (area, cell)."""
    rows, imgs = [], {}
    for a in range(4):
        for cx in range(4):
            for cy in range(4):
                img = np.full((72, 80), a * 60 + 40, np.uint8)
                img[:8] = cx * 20
                img[:, :8] = cy * 20
                i = f"a{a}x{cx}y{cy}"
                rows.append({"id": i, "area": f"map-{a}", "cell": f"{cx},{cy}",
                             "pos": [cx * 4, cy * 4], "count": 9})
                imgs[i] = img
    return rows, imgs


def test_parse_cell():
    assert location_data.parse_cell("3,7") == (3, 7)
    assert location_data.parse_cell("12") == (12,)


def test_assemble_shapes_weights_and_cells():
    rows, imgs = _thumbs()
    d = location_data.assemble(rows[:5], imgs.get)
    assert d["images"].shape == (5, 72, 80) and d["images"].dtype == np.uint8
    assert d["cells"].shape == (5, 2) and d["cells"][1].tolist() == [0, 1]
    assert (d["weights"] == 9).all()
    big = dict(rows[0])
    big["count"] = 99
    assert location_data.assemble([big], imgs.get)["weights"][0] == 20   # count capped


def test_nearest_baseline_recovers_area_and_cell_beside_trivial():
    rows, imgs = _thumbs()
    tr, te = split.split_thumbs_by_cell(rows, seed=0)
    d_tr = location_data.assemble(tr, imgs.get)
    d_te = location_data.assemble(te, imgs.get)
    idx = location_baseline.nearest(d_tr["images"], d_te["images"])
    assert idx.shape == (len(te),)
    pred_area = [d_tr["areas"][j] for j in idx]
    acc = report.accuracy(d_te["areas"], pred_area)
    assert acc == 1.0
    pred_cells = location_baseline.predict_cells(d_tr["cells"], idx)
    err, within = location_baseline.cell_error(d_te["cells"], pred_cells)
    assert err <= 2.0 and within >= 0.9                    # held-out cells -> neighbour thumbs
    triv_err, _ = location_baseline.cell_error(
        d_te["cells"],
        location_baseline.median_cell_predict(d_tr["areas"], d_tr["cells"], d_te["areas"]))
    assert err < triv_err
    rep = report.location_scores(acc, err, within, {}, len(te))
    assert rep["area_accuracy"] == 1.0 and rep["n"] == len(te)


def test_location_cnn_when_torch_present():
    pytest.importorskip("torch")
    from pokeagent.vision_motion import location_net
    rng = np.random.RandomState(0)
    rows, imgs = [], {}
    for a in range(3):
        base = rng.randint(0, 256, (72, 80)).astype(np.uint8)   # per-area texture
        for cx in range(3):
            for cy in range(3):
                img = (base // 4 + a * 60 + cx * 3 + cy).astype(np.uint8)
                i = f"a{a}x{cx}y{cy}"
                rows.append({"id": i, "area": f"map-{a}", "cell": f"{cx},{cy}",
                             "pos": [0, 0], "count": 1})
                imgs[i] = img
    tr, te = split.split_thumbs_by_cell(rows, seed=0)
    d_tr = location_data.assemble(tr, imgs.get)
    d_te = location_data.assemble(te, imgs.get)
    area_id = {a: i for i, a in enumerate(sorted(set(d_tr["areas"])))}
    t0 = time.perf_counter()
    net = location_net.train_net(d_tr["images"], [area_id[a] for a in d_tr["areas"]],
                                 d_tr["cells"], n_areas=len(area_id), seed=0, epochs=60)
    assert time.perf_counter() - t0 < 20
    assert location_net.param_count(net) < 40000
    pred, cells = location_net.predict(net, d_te["images"])
    acc = float((pred == np.array([area_id[a] for a in d_te["areas"]])).mean())
    assert acc > 0.9
    assert cells.shape == (len(te), 2)
    assert location_net.bench_ms(net, d_te["images"][0], runs=5, warmup=1) >= 0
