"""Read the area index (<source>/maps/index.json) and the area images, tolerantly.

The index is ``{"schema": 1, "<key>": {name: {"width", "height", "seen", "file"}}}`` where ``file``
is relative to ``<source>/maps/``. Columns not captured yet are white; ``seen`` is the captured
fraction. Anything unreadable or half-written yields nothing, never an exception: the writer's
next atomic write fixes it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Area:
    name: str
    width: int
    height: int
    seen: float
    path: Path


def load_areas(source: Path) -> list[Area]:
    """Index order is the area order used everywhere. Bad entries are skipped; a missing,
    empty, unreadable or invalid index returns []."""
    try:
        doc = json.loads((Path(source) / "maps" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict):
        return []
    entries = doc["areas"] if "areas" in doc else doc.get("levels")  # "levels" is the first writer's key name
    if not isinstance(entries, dict):
        return []
    out = []
    for name, e in entries.items():
        if not isinstance(e, dict):
            continue
        w, h, f = e.get("width"), e.get("height"), e.get("file")
        if not (type(w) is int and w > 0) or not (type(h) is int and h > 0) or not isinstance(f, str):
            continue
        path = Path(source) / "maps" / f
        if not path.is_file():
            continue
        try:
            seen = float(e.get("seen", 0.0))
        except (TypeError, ValueError):
            seen = 0.0
        out.append(Area(str(name), w, h, seen, path))
    return out


def load_image(area: Area) -> np.ndarray | None:
    """uint8 RGB (greyscale expanded to 3 channels); None when the file is missing or a
    partial image. The index and the image are written separately, so the decoded size may
    differ from the index: callers trust the image and replace the Area's size."""
    try:
        return np.asarray(Image.open(area.path).convert("RGB"), dtype=np.uint8)
    except (OSError, SyntaxError, ValueError):
        return None


class AreaStore:
    """Areas plus their decoded images; ``refresh`` reloads only files whose (mtime_ns, size)
    stamp changed, so a column that keeps growing simply yields a wider image next time."""

    def __init__(self) -> None:
        self.areas: list[Area] = []            # index order, image-true sizes
        self.images: dict[str, np.ndarray] = {}
        self._stamps: dict[str, tuple[int, int]] = {}
        self._loaded: dict[str, Area] = {}

    def refresh(self, source: Path) -> bool:
        changed = False
        keep: set[str] = set()
        areas: list[Area] = []
        for area in load_areas(source):
            keep.add(area.name)
            try:
                s = area.path.stat()
                stamp = (s.st_mtime_ns, s.st_size)
            except OSError:
                stamp = (-1, -1)
            cached = self._loaded.get(area.name)
            if cached is None or self._stamps.get(area.name) != stamp:
                img = load_image(area)
                if img is None:
                    if cached is None:
                        continue                 # unreadable now: retried on the next refresh
                    areas.append(replace(cached, seen=area.seen))   # keep the last good image
                    changed = changed or cached.seen != area.seen
                    continue
                cached = replace(area, width=int(img.shape[1]), height=int(img.shape[0]))
                self.images[area.name] = img
                self._loaded[area.name] = cached
                self._stamps[area.name] = stamp
                changed = True
            if cached.seen != area.seen:
                changed = True
            areas.append(replace(cached, seen=area.seen))
        if [a.name for a in areas] != [a.name for a in self.areas]:
            changed = True
        for name in set(self._loaded) - keep:
            del self._loaded[name]
            self.images.pop(name, None)
            self._stamps.pop(name, None)
            changed = True
        self.areas = areas
        return changed
