"""Turn a recorded vision dataset into padded numpy arrays for training."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pokeagent.vision.dataset import iter_samples, load_image

COARSE = ("enemy", "npc", "item", "player", "terrain", "other")
KINDS = ("sprite", "tile")
SIZE = 16
MAX_WEIGHT = 20.0


@dataclass(frozen=True)
class Dataset:
    """Padded crops plus the label columns a model trains on; ``ids`` is the content id."""

    images: np.ndarray  # (N,16,16,3) uint8, small crops top-left on a median-colour pad
    label: np.ndarray   # (N,) int32 raw label id
    coarse: np.ndarray  # (N,) int8 index into COARSE
    area: np.ndarray    # (N,) str area name
    kind: np.ndarray    # (N,) int8 index into KINDS
    bank: np.ndarray    # (N,) int32 tileset bank, -1 for None
    weight: np.ndarray  # (N,) float32 row count capped at MAX_WEIGHT
    w: np.ndarray       # (N,) int32 original crop width
    h: np.ndarray       # (N,) int32 original crop height
    ids: np.ndarray     # (N,) str content ids, for the train/test leak check

    def select(self, idx) -> "Dataset":
        """The subset at integer/bool index ``idx``."""
        return Dataset(self.images[idx], self.label[idx], self.coarse[idx], self.area[idx],
                       self.kind[idx], self.bank[idx], self.weight[idx], self.w[idx],
                       self.h[idx], self.ids[idx])


def _pad16(img: np.ndarray) -> np.ndarray:
    """Top-left on a 16x16 canvas of the crop's own median colour."""
    out = np.empty((SIZE, SIZE, 3), np.uint8)
    out[:] = np.median(img.reshape(-1, 3), axis=0).astype(np.uint8)
    h, w = min(img.shape[0], SIZE), min(img.shape[1], SIZE)
    out[:h, :w] = img[:h, :w]
    return out


def load_dataset(root, kinds=KINDS) -> Dataset:
    """Read samples.jsonl + PNG crops under ``root`` into one padded array set."""
    want = set(kinds)
    rows = [r for r in iter_samples(root) if r["kind"] in want]
    col = lambda k: [r[k] for r in rows]
    images = (np.stack([_pad16(load_image(root, r["id"])) for r in rows]) if rows
              else np.empty((0, SIZE, SIZE, 3), np.uint8))
    return Dataset(
        images=images,
        label=np.array(col("label"), np.int32),
        coarse=np.array([COARSE.index(r["coarse"]) for r in rows], np.int8),
        area=np.array(col("area")),
        kind=np.array([KINDS.index(r["kind"]) for r in rows], np.int8),
        bank=np.array([-1 if r["bank"] is None else r["bank"] for r in rows], np.int32),
        weight=np.minimum(np.array(col("count"), np.float32), MAX_WEIGHT),
        w=np.array(col("w"), np.int32),
        h=np.array(col("h"), np.int32),
        ids=np.array(col("id")))


def row_key(ds: Dataset, i: int) -> tuple:
    """The specific-class key of one row: (kind, bank, label); a tile id only means
    something inside its bank, so the bank stays in the key."""
    return (KINDS[int(ds.kind[i])], int(ds.bank[i]), int(ds.label[i]))


def class_table(ds: Dataset) -> dict:
    """Dense class id per distinct row key; a sprite id and a tile id never collide."""
    return {k: i for i, k in enumerate(sorted({row_key(ds, j)
                                             for j in range(len(ds.label))}))}


def encode(ds: Dataset, table: dict) -> np.ndarray:
    """Class id per row; -1 where the row's key is absent from ``table``."""
    return np.fromiter((table.get(row_key(ds, i), -1) for i in range(len(ds.label))),
                       np.int64, len(ds.label))


def class_name(key: tuple) -> str:
    """Readable name for a (kind, bank, label) key, e.g. ``tile:37@2``."""
    kind, bank, label = key
    return f"{kind}:{label}" + (f"@{bank}" if bank >= 0 else "")
