"""Nearest-template baseline: right class, same-kind candidates, bank rules, coarse."""
from __future__ import annotations

import numpy as np

from pokeagent.vision_model import data, template

SPRITE, TILE = (data.KINDS.index("sprite"), data.KINDS.index("tile"))
ENEMY, NPC, ITEM, TERRAIN = (data.COARSE.index("enemy"), data.COARSE.index("npc"),
                             data.COARSE.index("item"), data.COARSE.index("terrain"))


def synth():
    """Two sprite classes plus tiles: label 5 in two banks, label 9 in bank 0."""
    img = np.zeros((6, 16, 16, 3), np.uint8)
    img[0] = (200, 20, 20)
    img[1] = (190, 30, 30)        # sprite label 1, two crops (enemy)
    img[2] = (20, 200, 20)        # sprite label 2 (npc)
    img[3] = (30, 30, 220)        # tile label 5 bank 0 (terrain)
    img[4] = (220, 220, 30)       # tile label 5 bank 1 (terrain)
    img[5] = (100, 100, 100)      # tile label 9 bank 0 (item)
    return data.Dataset(
        img, np.array([1, 1, 2, 5, 5, 9], np.int32),
        np.array([ENEMY, ENEMY, NPC, TERRAIN, TERRAIN, ITEM], np.int8),
        np.array(["m0", "m0", "m0", "m0", "m1", "m0"]),
        np.array([SPRITE, SPRITE, SPRITE, TILE, TILE, TILE], np.int8),
        np.array([-1, -1, -1, 0, 1, 0], np.int32), np.ones(6, np.float32),
        np.full(6, 16, np.int32), np.full(6, 16, np.int32),
        np.array([f"i{k}" for k in range(6)]))


def solid(rgb):
    return np.full((16, 16, 3), rgb, np.uint8)


def test_classifies_patterns_and_respects_kind_and_bank():
    ds = synth()
    table = data.class_table(ds)
    t = template.fit_templates(ds, np.arange(len(ds.label)), table)
    imgs = np.stack([solid((205, 25, 25)), solid((35, 35, 215)),
                     solid((30, 30, 200)), solid((25, 25, 210)),
                     solid((205, 25, 25))])
    kind = np.array([SPRITE, TILE, TILE, TILE, TILE])
    bank = np.array([-1, 0, 1, 9, 0], np.int64)
    lab, co = template.predict_templates(t, imgs, kind, bank)
    assert lab[0] == table[("sprite", -1, 1)]     # red -> the red sprite class
    assert lab[1] == table[("tile", 0, 5)]        # blue tile in bank 0
    assert lab[2] == table[("tile", 1, 5)]        # blue-ish but bank 1 -> its own class
    assert lab[3] == table[("tile", 0, 5)]        # unknown bank -> all banks, nearest
    assert lab[4] == table[("tile", 0, 9)]        # marked tile: sprite classes excluded
    assert co[0] == ENEMY and co[2] == TERRAIN    # coarse of the nearest class


def test_batch_call_is_vectorised():
    ds = synth()
    table = data.class_table(ds)
    t = template.fit_templates(ds, np.arange(len(ds.label)), table)
    lab, co = template.predict_templates(t, ds.images, ds.kind, ds.bank)
    assert (lab == data.encode(ds, table)).all()  # every train crop maps to its class
    assert (co == ds.coarse.astype(np.int64)).all()
