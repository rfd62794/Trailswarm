"""dataset.py reads a written store back: tolerant of a truncated last line, typed arrays out."""
from __future__ import annotations

import json

import numpy as np

from pokeagent.vision import dataset
from pokeagent.vision.crops import content_id
from pokeagent.vision.positions import PositionLog
from pokeagent.vision.store import Store


def written(tmp_path):
    store = Store(tmp_path)
    arr8 = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    arr16 = np.full((16, 16, 3), 9, np.uint8)
    store.add_crop("tile", 7, "terrain", "map-5", "r0c0", 0, 0, 8, 8, 4, arr8)
    store.add_crop("sprite", 13, "npc", "map-5", "r1c1", 80, 60, 16, 16, None, arr16)
    t = np.arange(72 * 80, dtype=np.uint8).reshape(72, 80)
    store.add_thumb("map-5", "1,1", (5, 6), t)
    store.meta.update(game="pokemon-red", label_source="pokemon-red", sample_every=8, frames_seen=24)
    store.flush()
    log = PositionLog(tmp_path)
    log.append(32, "t", "map-5", (5, 6), [["slot1", 13, 6, 6, 254]])
    log.close()
    return {"arr8": arr8, "arr16": arr16, "t": t}


def test_reads_back_samples_images_thumbs_and_meta(tmp_path):
    made = written(tmp_path)
    meta = dataset.load_meta(tmp_path)
    assert meta["schema"] == 1 and meta["game"] == "pokemon-red" and meta["frames_seen"] == 24
    rows = list(dataset.iter_samples(tmp_path))
    assert {(r["kind"], r["label"]) for r in rows} == {("tile", 7), ("sprite", 13)}
    img = dataset.load_image(tmp_path, content_id(made["arr8"]))
    assert img.shape == (8, 8, 3) and img.dtype == np.uint8 and (img == made["arr8"]).all()
    thumbs = list(dataset.iter_thumbs(tmp_path))
    assert thumbs[0]["cell"] == "1,1" and thumbs[0]["pos"] == [5, 6]
    thumb = dataset.load_thumb(tmp_path, thumbs[0]["id"])
    assert thumb.shape == (72, 80) and thumb.dtype == np.uint8
    pos = list(dataset.iter_positions(tmp_path))
    assert pos == [{"f": 32, "run": "t", "area": "map-5", "player": [5, 6],
                    "ents": [["slot1", 13, 6, 6, 254]]}]


def test_truncated_last_line_is_tolerated(tmp_path):
    written(tmp_path)
    for name, reader in (("samples.jsonl", dataset.iter_samples),
                         ("thumbs.jsonl", dataset.iter_thumbs),
                         ("positions.jsonl", dataset.iter_positions)):
        path = tmp_path / name
        good = path.read_text()
        path.write_text(good + '{"id": "half')
        assert [r["id"] if "id" in r else r["f"] for r in reader(tmp_path)]  # full rows still read
