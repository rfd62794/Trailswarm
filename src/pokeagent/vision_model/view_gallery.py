"""Panels 2 and 3: per-class true-vs-predicted crops and the worst confusions."""
from __future__ import annotations

from collections import Counter, defaultdict

from PIL import Image

from pokeagent.vision_model.data import class_name, encode, row_key
from pokeagent.vision_model.view_draw import GREEN, GREY, RED, banner, cell, hstrip, up, vstack

K, SIZE = 4, 64


def crop_of(ds, i: int):
    """Row ``i``'s crop at its true size (the dataset pads to 16x16)."""
    return ds.images[i, :int(ds.h[i]), :int(ds.w[i])]


def exemplars(ds, train_idx, table) -> dict:
    """Class id -> first training row of that class."""
    ex = {}
    for j, c in zip(train_idx, encode(ds.select(train_idx), table)):
        ex.setdefault(int(c), int(j))
    return ex


def _pair(ds, i, pred_id, ex, true_id) -> Image.Image:
    """true crop | predicted class's exemplar (border green right, red wrong, grey unseen)."""
    border = GREY if true_id < 0 else (GREEN if pred_id == true_id else RED)
    p = (cell(up(crop_of(ds, ex[pred_id]), K), SIZE, border) if pred_id in ex
         else cell(Image.new("RGB", (8, 8)), SIZE, border))
    return hstrip([cell(up(crop_of(ds, i), K), SIZE), p], 2)


def _grid(title: str, blocks: list) -> Image.Image:
    return vstack([banner(600, title)] + [hstrip(blocks[i:i + 2], 16) for i in range(0, len(blocks), 2)], 8)


def class_gallery(ds, test_idx, pred, table, ex, top=20, per=5) -> Image.Image:
    """For the ``top`` classes by test support, ``per`` true crops each beside the exemplar
    of what the net predicted for it."""
    by = defaultdict(list)
    for i in test_idx:
        by[row_key(ds, int(i))].append(int(i))
    blocks = []
    for key, idx in sorted(by.items(), key=lambda kv: -len(kv[1]))[:top]:
        tid = table.get(key, -1)
        name = class_name(key) + (" (unseen)" if tid < 0 else "")
        pairs = [_pair(ds, i, int(pred[i]), ex, tid) for i in idx[:per]]
        blocks.append(vstack([banner(per * (SIZE * 2 + 6), f"{name}  n={len(idx)}", 14),
                              hstrip(pairs, 6)], 0))
    return _grid("each pair: true crop | what the net predicted (its class exemplar)", blocks)


def confusions(ds, test_idx, pred, table, ex, top=10, per=3):
    """(image, [(true name, predicted name, count)]) for the most frequent wrong pairs."""
    names = {v: class_name(k) for k, v in table.items()}
    cnt, eg = Counter(), defaultdict(list)
    for i in test_idx:
        key, p = row_key(ds, int(i)), int(pred[i])
        if table.get(key, -1) != p:
            cnt[(key, p)] += 1
            eg[(key, p)].append(int(i))
    blocks, info = [], []
    for (key, p), n in cnt.most_common(top):
        tid = table.get(key, -1)
        a, b = class_name(key) + (" (unseen)" if tid < 0 else ""), names[p]
        info.append((a, b, n))
        pairs = [_pair(ds, i, p, ex, tid) for i in eg[(key, p)][:per]]
        blocks.append(vstack([banner(per * (SIZE * 2 + 6), f"{a}  ->  {b}   x{n}", 14),
                              hstrip(pairs, 6)], 0))
    return _grid("true crop | predicted class exemplar, most frequent first", blocks), info
