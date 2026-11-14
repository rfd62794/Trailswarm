"""bench.measure*: documented keys with positive numbers; torch is optional."""
from __future__ import annotations

import numpy as np
import pytest

from pokeagent.vision_model import bench, data, template

KEYS = ("ms_per_crop", "ms_per_frame", "threads", "n_crops", "params")


def small_templates():
    img = np.zeros((3, 16, 16, 3), np.uint8)
    img[1] = 120
    img[2] = 240
    ds = data.Dataset(img, np.array([1, 2, 3], np.int32), np.zeros(3, np.int8),
                      np.array(["a", "a", "b"]), np.zeros(3, np.int8),
                      np.full(3, -1, np.int32), np.ones(3, np.float32),
                      np.full(3, 16, np.int32), np.full(3, 16, np.int32),
                      np.array(["x", "y", "z"]))
    return template.fit_templates(ds, np.arange(3), data.class_table(ds))


def test_measure_template_keys():
    rep = bench.measure_template(small_templates(), n_crops_per_frame=8, batches=5)
    for k in KEYS:
        assert rep[k] > 0
    assert rep["n_crops"] == 8


def test_measure_net_keys():
    pytest.importorskip("torch")
    from pokeagent.vision_model import net
    rep = bench.measure(net.TinyNet(4), n_crops_per_frame=8, batches=5)
    for k in KEYS:
        assert rep[k] > 0
    assert rep["n_crops"] == 8
