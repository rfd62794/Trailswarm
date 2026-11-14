"""Build every panel of the vision viewer as plain Pillow images and tables (no window).

``build`` is the one entry point; the Dear PyGui window (view_window) and the PNG writer
(``save_pngs``) both consume the ``Panels`` it returns. Torch is imported lazily.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.vision.dataset import iter_thumbs, load_thumb
from pokeagent.vision_model import data, split
from pokeagent.vision_model.view_draw import GREEN, GREY, RED
from pokeagent.vision_model.view_frames import frame_images, mosaic, pick_frame
from pokeagent.vision_model.view_gallery import class_gallery, confusions, crop_of, exemplars

MAX_THUMBS_PER_AREA = 40


@dataclass
class Panels:
    frames: list = field(default_factory=list)      # [(title, status image, coarse image, n boxes)]
    gallery: Image.Image | None = None
    confusions: Image.Image | None = None
    confusion_info: list = field(default_factory=list)
    filters: Image.Image | None = None
    activations: Image.Image | None = None
    arch: list = field(default_factory=list)        # [(layer, output shape, params)]
    numbers: list = field(default_factory=list)     # [(label, template, net)]


def out_allowed(out) -> bool:
    """The output directory must sit inside a ``runs`` directory (gitignored, local only)."""
    parts = Path(out).resolve().parts
    return "runs" in parts[:-1] or (len(parts) > 1 and parts[-1] == "runs")


def numbers(report: dict) -> list:
    """Headline [(label, template, net)] rows from a vision_train report.json."""
    t, n = report["template"], report["net"]
    rows = [(lab, f"{t[k]:.3f}", f"{n[k]:.3f}") for lab, k in
            (("overall accuracy", "overall"), ("weighted accuracy", "overall_weighted"),
             ("macro accuracy", "macro"), ("coarse accuracy", "coarse"))]
    rows.append(("test rows in classes never seen in training", "-", str(n["unseen_in_train"])))
    rows.append(("test rows / train rows", "-", f"{report['rows']['test']} / {report['rows']['train']}"))
    rows.append(("parameters", "-", str(report["params"])))
    return rows


def _frames(ds, thumbs_by_area, areas, root, status, coarse_name, count) -> list:
    out = []
    for area in areas[:count]:
        idx = np.flatnonzero(ds.area == area)
        crops = {int(i): (data.KINDS[int(ds.kind[i])], crop_of(ds, int(i))) for i in idx}
        th = thumbs_by_area.get(area, [])
        step = max(1, len(th) // MAX_THUMBS_PER_AREA)
        best = pick_frame(th[::step], crops, lambda tid: load_thumb(root, tid)) if th else None
        if best is not None and best[1]:
            a, b = frame_images(best[0], best[1], status, coarse_name)
            out.append((f"{area}", a, b, len(best[1])))
        else:
            cols = {"ok": GREEN, "wrong": RED, "unseen": GREY}
            m = mosaic(f"{area} (no frame rebuilt; crop mosaic)", [c for _, c in crops.values()],
                       [cols[status(r)] for r in crops])
            out.append((f"{area}", m, m, 0))
    return out


def build(root, model_dir, frames: int = 6) -> Panels:
    """Load the dataset and trained model, predict, and render every panel."""
    from pokeagent.vision_model import export, net, view_net

    root, model_dir = Path(root), Path(model_dir)
    report = json.loads((model_dir / "report.json").read_text(encoding="utf-8"))
    model, table = export.load(model_dir)
    ds = data.load_dataset(root)
    train_idx = split.area_indices(ds.area, set(report["areas"]["train"]))
    test_idx = split.area_indices(ds.area, set(report["areas"]["test"]))
    test_idx, _ = split.drop_leaking_test_rows(ds, train_idx, test_idx)
    pred, pco = net.predict(model, ds.images)
    enc = data.encode(ds, table)
    status = lambda i: "unseen" if enc[i] < 0 else ("ok" if pred[i] == enc[i] else "wrong")
    ex = exemplars(ds, train_idx, table)
    p = Panels(numbers=numbers(report), arch=view_net.architecture(model))
    thumbs: dict = {}
    for t in iter_thumbs(root):
        thumbs.setdefault(t["area"], []).append(t)
    test_areas = sorted(report["areas"]["test"])[:max(1, frames - 2)]
    train_areas = sorted(report["areas"]["train"], key=lambda a: -len(thumbs.get(a, [])))
    areas = test_areas + train_areas[:max(0, frames - len(test_areas))]
    for title, a, b, n in _frames(ds, thumbs, areas, root, status, lambda i: data.COARSE[int(pco[i])], frames):
        held = title in report["areas"]["test"]
        p.frames.append((f"{title} ({'held-out' if held else 'train'} area)", a, b, n))
    p.gallery = class_gallery(ds, test_idx, pred, table, ex)
    p.confusions, p.confusion_info = confusions(ds, test_idx, pred, table, ex)
    p.filters = view_net.conv1_filters(model)
    sample = [crop_of(ds, int(i)) for i in test_idx[:: max(1, len(test_idx) // 3)][:3]]
    p.activations = view_net.activation_maps(model, sample)
    return p


def save_pngs(p: Panels, out) -> list:
    """Write every panel as a PNG under ``out`` (must satisfy ``out_allowed``); returns paths."""
    out = Path(out)
    if not out_allowed(out):
        raise ValueError(f"refusing to write outside a runs/ directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    items = [(f"frame_{n:02d}_{kind}.png", im) for n, (_, a, b, _) in enumerate(p.frames, 1)
             for kind, im in (("status", a), ("coarse", b))]
    items += [("gallery.png", p.gallery), ("confusions.png", p.confusions),
              ("filters.png", p.filters), ("activations.png", p.activations)]
    paths = []
    for name, im in items:
        if im is not None:
            im.save(out / name)
            paths.append(out / name)
    return paths
