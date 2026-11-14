"""Measured inference cost on this machine: ms per crop and per frame of crops.

A frame's perception load is a batch of ``n_crops_per_frame`` 16x16 crops (up to ~15
sprites plus a few dozen distinct tiles). Numbers are measurements for the report,
never promises; the machine's CPU count travels with them.
"""
from __future__ import annotations

import os
import time

import numpy as np

WARMUP = 10


def _report(times, n_crops, threads, params, batches) -> dict:
    ms = float(np.median(times) * 1000.0)
    return {"ms_per_crop": ms / n_crops, "ms_per_frame": ms, "threads": threads,
            "n_crops": n_crops, "params": int(params), "batches": batches,
            "cpus": os.cpu_count() or 1}


def measure(model, n_crops_per_frame=60, batches=200, threads=1) -> dict:
    """Median wall time of one frame's crops through the torch model."""
    import torch

    torch.set_num_threads(threads)
    frame = np.random.default_rng(0).integers(
        0, 256, (n_crops_per_frame, 16, 16, 3), dtype=np.uint8)
    model.eval()

    def once():
        with torch.no_grad():
            x = (torch.from_numpy(frame).float().div_(255.0).permute(0, 3, 1, 2))
            model(x)

    for _ in range(WARMUP):
        once()
    times = []
    for _ in range(batches):
        t0 = time.perf_counter()
        once()
        times.append(time.perf_counter() - t0)
    return _report(times, n_crops_per_frame, threads,
                   sum(p.numel() for p in model.parameters()), batches)


def measure_template(templates, n_crops_per_frame=60, batches=200, threads=1) -> dict:
    """The same measurement for the nearest-template baseline (pure numpy)."""
    from pokeagent.vision_model.template import predict_templates

    frame = np.random.default_rng(0).integers(
        0, 256, (n_crops_per_frame, 16, 16, 3), dtype=np.uint8)
    kind = np.zeros(n_crops_per_frame, np.int64)
    bank = np.full(n_crops_per_frame, -1, np.int64)
    for _ in range(WARMUP):
        predict_templates(templates, frame, kind, bank)
    times = []
    for _ in range(batches):
        t0 = time.perf_counter()
        predict_templates(templates, frame, kind, bank)
        times.append(time.perf_counter() - t0)
    return _report(times, n_crops_per_frame, threads, templates.means.size, batches)
