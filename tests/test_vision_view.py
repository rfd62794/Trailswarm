"""Vision viewer: rendering functions on synthetic data only (no ROM, no runs/ data, no window)."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from pokeagent.vision.crops import thumb
from pokeagent.vision_model import data, view
from pokeagent.vision_model.view_draw import GREEN, RED, to_rgba_floats, up
from pokeagent.vision_model.view_frames import find_boxes, frame_images, mosaic, overlay
from pokeagent.vision_model.view_gallery import class_gallery, confusions, exemplars


def frame_with_tile():
    rng = np.random.default_rng(0)
    frame = np.full((144, 160, 3), 255, np.uint8)
    tile = rng.integers(0, 255, (8, 8, 3), dtype=np.uint8)
    frame[16:24, 8:16] = tile
    return frame, tile


def synth_ds():
    """6 rows: two tile classes (bank 0) and one sprite; 'b' tiles are the confusable ones."""
    rng = np.random.default_rng(1)
    n = 6
    imgs = rng.integers(0, 255, (n, 16, 16, 3), dtype=np.uint8)
    return data.Dataset(
        images=imgs, label=np.array([1, 1, 2, 2, 2, 7], np.int32),
        coarse=np.array([4, 4, 4, 4, 4, 1], np.int8), area=np.array(["a", "a", "b", "b", "b", "b"]),
        kind=np.array([1, 1, 1, 1, 1, 0], np.int8), bank=np.array([0, 0, 0, 0, 0, -1], np.int32),
        weight=np.ones(n, np.float32), w=np.full(n, 8, np.int32), h=np.full(n, 8, np.int32),
        ids=np.array([f"id{i}" for i in range(n)]))


def test_up_and_texture_floats():
    im = up(np.zeros((3, 5), np.uint8), 4)
    assert im.size == (20, 12)
    w, h, flat = to_rgba_floats(Image.new("RGB", (6, 2), (255, 0, 0)))
    assert (w, h, flat.shape, flat.dtype) == (6, 2, (48,), np.float32)
    assert flat.max() == 1.0 and tuple(flat[:4]) == (1.0, 0.0, 0.0, 1.0)


def test_find_boxes_and_overlay_colours():
    frame, tile = frame_with_tile()
    th = thumb(frame)
    boxes = find_boxes(th, {5: ("tile", tile)})
    assert (8, 16, 8, 8, 5) in boxes
    im = overlay(th, [(8, 16, 8, 8, 5)], lambda r: GREEN, False)
    assert im.size == (320, 288)
    assert im.getpixel((8 // 2 * 4, 16 // 2 * 4)) == GREEN
    a, b = frame_images(th, [(8, 16, 8, 8, 5)], lambda r: "wrong", lambda r: "npc")
    assert a.getpixel((16, 32)) == RED and a.size == b.size == (320, 288)
    assert b.getpixel((17, 33)) != a.getpixel((17, 33))          # filled, not outlined


def test_mosaic_fallback():
    m = mosaic("t", [np.zeros((8, 8, 3), np.uint8)] * 30, [GREEN] * 30, k=2, cols=10)
    assert m.width >= 10 * 16 and m.height > 16 * 3


def test_gallery_and_confusions():
    ds = synth_ds()
    table = data.class_table(ds.select(np.array([0, 1, 2, 3, 4])))
    train, test = np.array([0, 1]), np.array([2, 3, 4, 5])
    ex = exemplars(ds, train, table)
    pred = np.array([0, 0, 0, 0, 1, 0])        # class ids: tile:1@0 -> 0, tile:2@0 -> 1
    img = class_gallery(ds, test, pred, table, ex)
    assert img.width > 100 and img.height > 100
    conf, info = confusions(ds, test, pred, table, ex)
    assert info[0][2] == 2 and info[0][0].startswith("tile:2") and info[0][1].startswith("tile:1")
    assert any("(unseen)" in a for a, _, _ in info)   # the sprite class is not in the table


def test_numbers_rows():
    rep = {"template": {"overall": 0.1, "overall_weighted": 0.2, "macro": 0.3, "coarse": 0.9},
           "net": {"overall": 0.5, "overall_weighted": 0.6, "macro": 0.7, "coarse": 0.99,
                   "unseen_in_train": 4}, "rows": {"test": 10, "train": 20}, "params": 123}
    rows = view.numbers(rep)
    assert rows[0] == ("overall accuracy", "0.100", "0.500") and rows[-1][2] == "123"


def test_output_guard(tmp_path):
    assert view.out_allowed(tmp_path / "runs" / "vision_models" / "x" / "view")
    assert view.out_allowed(tmp_path / "other" / "runs" / "v")
    assert not view.out_allowed(tmp_path / "docs" / "view")
    with pytest.raises(ValueError):
        view.save_pngs(view.Panels(), tmp_path / "docs")


def test_save_pngs_under_runs(tmp_path):
    p = view.Panels(frames=[("a", Image.new("RGB", (4, 4)), Image.new("RGB", (4, 4)), 0)],
                    gallery=Image.new("RGB", (5, 5)))
    paths = view.save_pngs(p, tmp_path / "runs" / "view")
    assert sorted(x.name for x in paths) == ["frame_01_coarse.png", "frame_01_status.png", "gallery.png"]


def test_net_panels():
    pytest.importorskip("torch")
    from pokeagent.vision_model import net, view_net
    model = net.TinyNet(12)
    assert view_net.conv1_filters(model).width > 100
    crops = [np.zeros((8, 8, 3), np.uint8), np.full((16, 16, 3), 200, np.uint8)]
    assert view_net.activation_maps(model, crops).height > 100
    arch = view_net.architecture(model)
    assert sum(n for _, _, n in arch) == net.param_count(model)
    assert arch[0][1] == (16, 16, 16) and arch[-1][1] == (6,)
