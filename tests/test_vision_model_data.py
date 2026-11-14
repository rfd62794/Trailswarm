"""load_dataset: 16x16 padding, weight cap, bank-keyed tile classes, kinds filter."""
from __future__ import annotations

import numpy as np

from pokeagent.vision.store import Store
from pokeagent.vision_model import data


def written(tmp_path):
    """Three crops: a banked tile seen 40x, a sprite with the same label id, a tile in
    another bank."""
    store = Store(tmp_path)
    tile = np.zeros((8, 8, 3), np.uint8)
    tile[:5] = 10
    tile[5:] = 60                                   # per-channel median colour is 10
    sprite = np.full((16, 16, 3), 200, np.uint8)
    other = np.full((8, 8, 3), 30, np.uint8)
    for _ in range(40):
        store.add_crop("tile", 7, "terrain", "map-1", "r0c0", 0, 0, 8, 8, 2, tile)
    store.add_crop("sprite", 7, "npc", "map-1", "r1c1", 3, 4, 16, 16, None, sprite)
    store.add_crop("tile", 7, "terrain", "map-2", "r0c0", 0, 0, 8, 8, 5, other)
    store.flush()
    return tile, sprite, other


def test_load_pads_to_16_and_caps_weight(tmp_path):
    tile, sprite, _ = written(tmp_path)
    ds = data.load_dataset(tmp_path)
    assert ds.images.shape == (3, 16, 16, 3) and ds.images.dtype == np.uint8
    i = int(np.flatnonzero(ds.w == 8)[0])           # the first tile row
    assert (ds.images[i, :8, :8] == tile).all()     # crop top-left
    assert (ds.images[i, 8:, :] == 10).all()        # pad is the crop's median colour
    assert (ds.images[i, :8, 8:] == 10).all()
    assert ds.w[i] == 8 and ds.h[i] == 8            # original size kept
    assert ds.weight[i] == data.MAX_WEIGHT == 20.0  # 40 sightings capped
    j = int(np.flatnonzero(ds.kind == data.KINDS.index("sprite"))[0])
    assert (ds.images[j] == sprite).all() and ds.weight[j] == 1.0


def test_bank_kind_and_class_table(tmp_path):
    written(tmp_path)
    ds = data.load_dataset(tmp_path)
    table = data.class_table(ds)
    assert set(table) == {("tile", 2, 7), ("sprite", -1, 7), ("tile", 5, 7)}
    assert (data.encode(ds, table) >= 0).all()
    # a sprite id and a tile id never collide, and a tile id keeps its bank
    assert table[("tile", 2, 7)] != table[("sprite", -1, 7)]
    assert table[("tile", 2, 7)] != table[("tile", 5, 7)]
    assert ds.bank[ds.kind == data.KINDS.index("sprite")].tolist() == [-1]


def test_kinds_filter_and_select(tmp_path):
    written(tmp_path)
    ds = data.load_dataset(tmp_path, kinds=("sprite",))
    assert len(ds.label) == 1 and ds.kind[0] == data.KINDS.index("sprite")
    full = data.load_dataset(tmp_path)
    sub = full.select(np.array([1, 2]))
    assert len(sub.label) == 2 and (sub.ids == full.ids[1:]).all()
    assert sub.coarse.tolist() == [data.COARSE.index("npc"),
                                   data.COARSE.index("terrain")]
