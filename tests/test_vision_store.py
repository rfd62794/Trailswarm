"""Store: content dedupe, count on repeats, byte/per-key/thumb caps for NEW images only, atomic
flush, and resuming counts from an existing root."""
from __future__ import annotations

import json

import numpy as np

from pokeagent.vision.crops import content_id
from pokeagent.vision.store import Store


def arr(n, h=8, w=8):
    return np.full((h, w, 3), n, np.uint8)


def crop_args(n, area="map-5"):
    return ("sprite", 13, "npc", area, "r1c1", 80, 60, 8, 8, None, arr(n))


def rows(root, name="samples.jsonl"):
    return [json.loads(ln) for ln in (root / name).read_text().splitlines()]


def test_one_png_per_unique_content_and_count_on_repeats(tmp_path):
    store = Store(tmp_path)
    cid = store.add_crop(*crop_args(1))
    store.add_crop(*crop_args(1))
    store.add_crop(*crop_args(2))
    store.flush()
    assert cid == content_id(arr(1))
    assert list((tmp_path / "images" / cid[:2]).glob("*.png")) == [tmp_path / "images" / cid[:2] / f"{cid}.png"]
    assert len(list((tmp_path / "images").rglob("*.png"))) == 2
    got = {r["id"]: r for r in rows(tmp_path)}
    assert got[cid]["count"] == 2 and got[cid]["coarse"] == "npc" and got[cid]["region"] == "r1c1"
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["schema"] == 1 and "bytes" in meta and "caps" in meta


def test_max_per_key_refuses_new_images_but_still_counts_existing(tmp_path):
    store = Store(tmp_path, max_per_key=2)
    assert store.add_crop(*crop_args(1)) and store.add_crop(*crop_args(2))
    assert store.add_crop(*crop_args(3)) is None                 # third distinct image refused
    assert store.add_crop(*crop_args(1)) is not None             # an existing image still counts
    other_area = ("sprite", 13, "npc", "map-6", "r0c0", 0, 0, 8, 8, None, arr(3))
    assert store.add_crop(*other_area) is not None               # a different key is not capped
    assert len(list((tmp_path / "images").rglob("*.png"))) == 3


def test_max_bytes_refuses_new_images_only(tmp_path):
    store = Store(tmp_path, max_bytes=1)
    cid = store.add_crop(*crop_args(1))
    assert cid and store.full
    assert store.add_crop(*crop_args(2)) is None
    assert store.add_crop(*crop_args(1)) == cid                  # count still lands
    store.flush()
    assert {r["id"] for r in rows(tmp_path)} == {cid}


def test_thumbs_cap_and_dedupe(tmp_path):
    store = Store(tmp_path, max_thumbs=2)
    t1, t2, t3 = np.full((72, 80), 1, np.uint8), np.full((72, 80), 2, np.uint8), np.full((72, 80), 3, np.uint8)
    assert store.add_thumb("map-5", "1,1", (5, 6), t1)
    assert store.add_thumb("map-5", "1,1", (5, 6), t1)           # repeat: count, no new write
    assert store.add_thumb("map-5", "1,1", (5, 6), t2)
    assert store.add_thumb("map-5", "1,1", (5, 6), t3) is None   # max_thumbs reached
    store.flush()
    thumbs = {r["id"]: r for r in rows(tmp_path, "thumbs.jsonl")}
    assert len(list((tmp_path / "thumbs").rglob("*.png"))) == 2
    assert thumbs[content_id(t1)]["count"] == 2 and thumbs[content_id(t1)]["pos"] == [5, 6]


def test_second_store_continues_counts_from_the_first(tmp_path):
    store = Store(tmp_path)
    store.add_crop(*crop_args(1))
    store.flush()
    again = Store(tmp_path)
    cid = content_id(arr(1))
    assert again.add_crop(*crop_args(1)) == cid                  # no duplicate PNG
    again.flush()
    assert len(list((tmp_path / "images").rglob("*.png"))) == 1
    assert {r["id"]: r["count"] for r in rows(tmp_path)} == {cid: 2}
