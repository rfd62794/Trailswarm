"""triage: one bucket per held-out row by precedence; confident-wrong ranking.

The torch test skips cleanly where torch is absent (the vision group is
optional).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pokeagent.vision_model import triage

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["cls:a", "cls:b", "cls:c", "cls:d (unseen)"]


def rows():
    """One row per bucket, plus a row that is both unseen and coarse-wrong."""
    true = np.array([0, 3, 1, 3, 2])     # class 3 is absent from train
    pred = np.array([0, 0, 2, 0, 0])
    tco = np.array([0, 4, 1, 4, 2])
    pco = np.array([0, 4, 1, 5, 3])      # rows 3 and 4 miss the coarse class
    conf = np.array([0.9, 0.7, 0.6, 0.8, 0.5])
    ids = np.array(["id-correct", "id-unseen", "id-fine", "id-both",
                    "id-coarse"])
    train = {0, 1, 2}
    return true, pred, tco, pco, conf, train, ids


def test_every_row_one_bucket_counts_sum():
    res = triage.triage(*rows(), class_names=NAMES)
    assert res["n"] == 5
    assert res["counts"] == {"correct": 1, "unseen_in_train": 2,
                             "coarse_wrong": 1, "coarse_right_fine_wrong": 1}
    assert sum(res["counts"].values()) == res["n"]
    assert res["wrong"] == res["n"] - res["counts"]["correct"]
    assert set(res["counts"]) == set(triage.BUCKETS)


def test_precedence_unseen_beats_coarse_wrong():
    res = triage.triage(*rows(), class_names=NAMES)
    by_id = {e["id"]: e["bucket"] for e in res["confident_wrong"]}
    assert by_id["id-both"] == "unseen_in_train"     # unseen AND coarse wrong
    assert by_id["id-unseen"] == "unseen_in_train"
    assert by_id["id-fine"] == "coarse_right_fine_wrong"
    assert by_id["id-coarse"] == "coarse_wrong"
    assert "id-correct" not in by_id


def test_confident_wrong_sorted_capped_json():
    true, pred, tco, pco, conf, train, ids = rows()
    conf = conf.copy()
    conf[4] = 0.6                                    # tie with row 2
    res = triage.triage(true, pred, tco, pco, conf, train, ids,
                        class_names=NAMES, top_n=3)
    entries = res["confident_wrong"]
    assert len(entries) == 3
    assert all(set(e) == {"id", "true", "pred", "confidence", "bucket"}
               for e in entries)
    # id ascending breaks the 0.6 tie: "id-coarse" < "id-fine"
    assert [e["id"] for e in entries] == ["id-both", "id-unseen", "id-coarse"]
    assert [e["confidence"] for e in entries] == [0.8, 0.7, 0.6]
    assert all(isinstance(e["confidence"], float) for e in entries)
    json.dumps(res)


def test_deterministic_across_calls_and_shuffle():
    true, pred, tco, pco, conf, train, ids = rows()
    r1 = triage.triage(true, pred, tco, pco, conf, train, ids,
                       class_names=NAMES)
    r2 = triage.triage(true, pred, tco, pco, conf, train, ids,
                       class_names=NAMES)
    assert r1 == r2
    perm = np.random.default_rng(0).permutation(len(true))
    r3 = triage.triage(true[perm], pred[perm], tco[perm], pco[perm],
                       conf[perm], train, ids[perm], class_names=NAMES)
    assert r3["counts"] == r1["counts"]
    assert r3["confident_wrong"] == r1["confident_wrong"]


def test_validation_empty_and_unknown_names():
    true, pred, tco, pco, conf, train, ids = rows()
    with pytest.raises(ValueError):
        triage.triage(true[:2], pred, tco, pco, conf, train, ids)
    with pytest.raises(ValueError):
        triage.triage(true, pred, tco, pco, conf, train, ids, top_n=-1)
    empty = triage.triage(true[:0], pred[:0], tco[:0], pco[:0], conf[:0],
                          train, ids[:0])
    assert empty["n"] == 0 and empty["wrong"] == 0
    assert empty["counts"] == {b: 0 for b in triage.BUCKETS}
    assert empty["confident_wrong"] == []
    res = triage.triage(np.array([9]), np.array([8]), np.array([0]),
                        np.array([0]), np.array([0.5]), {0, 1},
                        np.array(["x"]), class_names=NAMES)
    assert res["confident_wrong"][0]["true"] == "?"
    assert res["confident_wrong"][0]["pred"] == "?"
    res2 = triage.triage(np.array([0]), np.array([1]), np.array([0]),
                         np.array([0]), np.array([0.5]), {0, 1},
                         np.array(["x"]))
    assert res2["confident_wrong"][0]["true"] == "?"


def test_format_text_buckets_and_cap():
    res = triage.triage(*rows(), class_names=NAMES)
    text = triage.format_text(res, top=2)
    for b in triage.BUCKETS:
        assert b in text
    lines = text.splitlines()
    assert len(lines) == 3                           # counts + 2 entries
    assert "id-corre" not in text                    # the correct row stays out


def test_triage_imports_without_torch():
    """sys.modules['torch'] = None makes any `import torch` raise ImportError."""
    code = ("import sys\nsys.modules['torch'] = None\n"
            "import pokeagent.vision_model.triage\nprint('ok')\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = (str(ROOT / "src") + os.pathsep
                         + env.get("PYTHONPATH", ""))
    p = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr


def test_triage_has_no_torch_and_is_small():
    src = (ROOT / "src" / "pokeagent" / "vision_model" / "triage.py"
           ).read_text(encoding="utf-8")
    assert "torch" not in src
    assert len(src.splitlines()) < 150


def test_predict_with_confidence_matches_predict():
    pytest.importorskip("torch")
    from pokeagent.vision_model import net
    model = net.TinyNet(4)
    imgs = np.random.default_rng(0).integers(0, 255, (8, 16, 16, 3),
                                             dtype=np.uint8)
    l1, c1 = net.predict(model, imgs)
    l2, c2, conf = net.predict_with_confidence(model, imgs)
    assert (l1 == l2).all() and (c1 == c2).all()
    assert conf.dtype == np.float32
    assert (conf >= 1 / 4).all() and (conf <= 1).all()
    _, _, conf2 = net.predict_with_confidence(model, imgs)
    assert (conf == conf2).all()
