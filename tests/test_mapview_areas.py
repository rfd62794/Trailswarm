import json
import os
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.mapview.areas import Area, AreaStore, load_areas, load_image


def png(path: Path, w: int, h: int, seed: int = 0) -> None:
    x = (np.arange(w)[None, :] + np.arange(h)[:, None] * 3 + seed) % 200
    Image.fromarray(x.astype(np.uint8), "L").save(path)


def make_source(tmp_path: Path, entries=("a-1", "b-1"), key="levels") -> Path:
    maps = tmp_path / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    idx = {}
    for i, name in enumerate(entries):
        fn = f"area_{name}.png"
        png(maps / fn, 20 + 10 * i, 12, i)
        idx[name] = {"width": 20 + 10 * i, "height": 12, "seen": 0.4 + i * 0.1, "file": fn}
    (maps / "index.json").write_text(json.dumps({"schema": 1, key: idx}), encoding="utf-8")
    return tmp_path


def test_load_areas_reads_first_writer_key_and_alias(tmp_path):
    areas = load_areas(make_source(tmp_path))
    assert [a.name for a in areas] == ["a-1", "b-1"]              # index order kept
    assert (areas[0].width, areas[0].height, areas[0].seen) == (20, 12, 0.4)
    aliased = load_areas(make_source(tmp_path / "alt", key="areas"))
    assert [a.name for a in aliased] == ["a-1", "b-1"]            # the alias reads the same


def test_load_areas_skips_missing_file_and_bad_size(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    png(maps / "ok.png", 10, 10)
    idx = {"good": {"width": 10, "height": 10, "seen": 1.0, "file": "ok.png"},
           "gone": {"width": 5, "height": 5, "file": "gone.png"},
           "wide": {"width": "10", "height": 10, "file": "ok.png"},
           "flat": {"width": 10, "height": 0, "file": "ok.png"},
           "neg": {"width": -3, "height": 4, "file": "ok.png"},
           "nofile": {"width": 10, "height": 10}}
    (maps / "index.json").write_text(json.dumps({"schema": 1, "levels": idx}), encoding="utf-8")
    assert [a.name for a in load_areas(tmp_path)] == ["good"]


def test_load_areas_never_raises(tmp_path):
    assert load_areas(tmp_path / "missing") == []
    maps = tmp_path / "maps"
    maps.mkdir()
    assert load_areas(tmp_path) == []                             # no index at all
    (maps / "index.json").write_text("")
    assert load_areas(tmp_path) == []                             # empty file
    (maps / "index.json").write_text('{"schema": 1, "lev')
    assert load_areas(tmp_path) == []                             # half-written
    (maps / "index.json").write_text("[1, 2]")
    assert load_areas(tmp_path) == []                             # not a dict
    (maps / "index.json").write_text('{"schema": 1, "levels": "x"}')
    assert load_areas(tmp_path) == []


def test_load_image(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    p = maps / "a.png"
    png(p, 20, 12)
    img = load_image(Area("a", 999, 999, 0.0, p))                 # index size wrong on purpose
    assert img is not None and img.shape == (12, 20, 3) and img.dtype == np.uint8
    assert (img[..., 0] == img[..., 1]).all()                     # greyscale expanded to RGB
    assert load_image(Area("m", 5, 5, 0.0, maps / "missing.png")) is None
    p.write_bytes(p.read_bytes()[:30])
    assert load_image(Area("a", 20, 12, 0.0, p)) is None          # truncated PNG


def test_area_store_refresh_reloads_only_changes(tmp_path):
    src = make_source(tmp_path)
    store = AreaStore()
    assert store.refresh(src) is True
    assert [a.width for a in store.areas] == [20, 30]
    assert store.refresh(src) is False                            # nothing changed: no reload
    victim = store.areas[0].path
    png(victim, 64, 12, 5)
    os.utime(victim, (1_800_000_000, 1_800_000_000))
    assert store.refresh(src) is True
    assert store.areas[0].width == 64                             # the image wins over the index
    assert store.refresh(src) is False


def test_changed_image_that_fails_to_decode_keeps_the_cached_area(tmp_path):
    src = make_source(tmp_path)
    store = AreaStore()
    store.refresh(src)
    before = [a.name for a in store.areas]
    img = store.images["a-1"]
    (src / "maps" / "area_a-1.png").write_bytes(b"not a png at all")
    store.refresh(src)
    assert [a.name for a in store.areas] == before and store.images["a-1"] is img
