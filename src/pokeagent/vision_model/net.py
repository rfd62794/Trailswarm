"""Tiny CNN over a 16x16 crop: a specific-class head plus a 6-way coarse head.

Torch is imported inside function bodies only, so this module imports cleanly on a
machine without torch; the training and prediction entry points are the only users.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from pokeagent.vision_model.data import COARSE, encode

N_COARSE = len(COARSE)


def TinyNet(n_classes: int):
    """3x(3x3 conv + ReLU + 2x2 pool) -> global average pool -> two linear heads."""
    import torch.nn as nn

    class _Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(3, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2))
            self.class_head = nn.Linear(32, n_classes)
            self.coarse_head = nn.Linear(32, N_COARSE)

        def forward(self, x):
            f = self.features(x).mean(dim=(2, 3))
            return self.class_head(f), self.coarse_head(f)

    return _Net()


def param_count(model) -> int:
    """Total trainable parameters; must stay under 30 000 for ``n_classes <= 200``."""
    return int(sum(p.numel() for p in model.parameters()))


@dataclass(frozen=True)
class TrainResult:
    """What one ``train`` call did; ``stopped_by_clock`` marks the wall-clock stop."""

    model: object
    epochs: int
    seconds: float
    stopped_by_clock: bool
    loss: float


def _tensors(ds, idx, table):
    import torch

    x = (torch.from_numpy(np.ascontiguousarray(ds.images[idx])).float().div_(255.0)
         .permute(0, 3, 1, 2).contiguous())
    y = torch.from_numpy(encode(ds.select(idx), table))
    if int((y < 0).sum()):
        raise ValueError("train rows contain classes missing from the table")
    c = torch.from_numpy(ds.coarse[idx].astype(np.int64))
    w = torch.from_numpy(ds.weight[idx].astype(np.float32))
    return x, y, c, w


def train(ds, train_idx, table, *, epochs=30, batch=128, lr=2e-3, seed=0,
          threads=1, max_seconds=300) -> TrainResult:
    """Adam on weighted CE(class) + 0.5*CE(coarse), CPU only. Augmentation is a +-1px
    shift and a +-10% brightness jitter - both keep the label true; no horizontal flip
    (facing matters to some classes). Stops at an epoch boundary past max_seconds."""
    import torch
    import torch.nn.functional as F

    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    rng = np.random.default_rng(seed)
    model = TinyNet(len(table))
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    X, Y, C, W = _tensors(ds, np.asarray(train_idx), table)
    n, t0, last, hit = len(Y), time.perf_counter(), 0.0, False
    ep = 0
    for ep in range(1, epochs + 1):
        model.train()
        total = 0.0
        perm = rng.permutation(n)
        for s in range(0, n, batch):
            b = perm[s:s + batch]
            xb = torch.roll(X[b], shifts=(int(rng.integers(-1, 2)),
                                          int(rng.integers(-1, 2))), dims=(2, 3))
            gain = torch.from_numpy(rng.uniform(0.9, 1.1, (len(b), 1, 1, 1))
                                    .astype(np.float32))
            logits, co = model((xb * gain).clamp_(0.0, 1.0))
            per = (F.cross_entropy(logits, Y[b], reduction="none")
                   + 0.5 * F.cross_entropy(co, C[b], reduction="none"))
            loss = (per * W[b]).sum() / W[b].sum()
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss)
        last = total / max(1, -(-n // batch))
        if time.perf_counter() - t0 >= max_seconds:
            hit = True
            break
    return TrainResult(model, ep, time.perf_counter() - t0, hit, last)


def predict(model, images, batch=512) -> tuple[np.ndarray, np.ndarray]:
    """(class id, coarse id) per crop; deterministic, no grad."""
    import torch

    model.eval()
    lab = np.empty(len(images), np.int64)
    co = np.empty(len(images), np.int64)
    with torch.no_grad():
        for s in range(0, len(images), batch):
            x = (torch.from_numpy(np.ascontiguousarray(images[s:s + batch]))
                 .float().div_(255.0).permute(0, 3, 1, 2))
            logits, coarse = model(x)
            lab[s:s + batch] = logits.argmax(1).numpy()
            co[s:s + batch] = coarse.argmax(1).numpy()
    return lab, co


def predict_with_confidence(model, images, batch=512) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(class id, coarse id, confidence) per crop; confidence is the max
    softmax of the class head."""
    import torch

    model.eval()
    lab = np.empty(len(images), np.int64)
    co = np.empty(len(images), np.int64)
    conf = np.empty(len(images), np.float32)
    with torch.no_grad():
        for s in range(0, len(images), batch):
            x = (torch.from_numpy(np.ascontiguousarray(images[s:s + batch]))
                 .float().div_(255.0).permute(0, 3, 1, 2))
            logits, coarse = model(x)
            lab[s:s + batch] = logits.argmax(1).numpy()
            co[s:s + batch] = coarse.argmax(1).numpy()
            conf[s:s + batch] = torch.softmax(logits, 1).max(1).values.numpy()
    return lab, co, conf
