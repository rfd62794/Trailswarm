"""Deduplicating dataset writer: content-keyed PNGs plus atomic jsonl indexes.

Layout under ``root`` (all local, gitignored): ``images/<hh>/<sha1>.png`` unique crops,
``samples.jsonl`` one row per unique (kind, label, area, image), ``thumbs/<hh>/<sha1>.png``
80x72 frame thumbnails, ``thumbs.jsonl`` one row per unique (area, cell, image), and
``meta.json``. Re-opening a written root continues its counts instead of duplicating.
"""
from __future__ import annotations

import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.vision.crops import content_id

MAX_BYTES = 200_000_000     # cap on the running byte total (PNGs written + index sizes)
MAX_PER_KEY = 40            # distinct images kept per (kind, label, area): bounds common terrain
MAX_THUMBS = 3000           # distinct thumbnails kept
RETIRES, RETRY_S = 40, 0.05


def write_atomic(path: Path, write) -> None:
    """Write to a temp file beside ``path``, then os.replace; retries a shared-machine transient."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp{path.suffix}")
    write(tmp)
    for _ in range(RETIRES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(RETRY_S)
    tmp.unlink(missing_ok=True)


def _jsonl_rows(path: Path) -> list[dict]:
    out = []
    if path.is_file():
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                break             # a half-written last line (a flush killed mid-write)
    return out


def _png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


class Store:
    def __init__(self, root, *, max_bytes: int = MAX_BYTES, max_per_key: int = MAX_PER_KEY,
                 max_thumbs: int = MAX_THUMBS) -> None:
        self.root = Path(root)
        self.max_bytes, self.max_per_key, self.max_thumbs = max_bytes, max_per_key, max_thumbs
        self.meta: dict = {}
        self._bytes = sum(p.stat().st_size for p in self.root.rglob("*.png")) if self.root.is_dir() else 0
        (self.root / "images").mkdir(parents=True, exist_ok=True)
        (self.root / "thumbs").mkdir(parents=True, exist_ok=True)
        self._samples: dict[tuple, dict] = {}
        self._seen: set[str] = set()
        self._per_key: dict[tuple, set] = {}
        for r in _jsonl_rows(self.root / "samples.jsonl"):
            self._samples[(r["kind"], r["label"], r["area"], r["id"])] = r
            self._seen.add(r["id"])
            self._per_key.setdefault((r["kind"], r["label"], r["area"]), set()).add(r["id"])
        self._thumbs: dict[tuple, dict] = {}
        self._tseen: set[str] = set()
        for r in _jsonl_rows(self.root / "thumbs.jsonl"):
            self._thumbs[(r["area"], r["cell"], r["id"])] = r
            self._tseen.add(r["id"])

    @property
    def bytes(self) -> int:
        """The running byte total: PNGs written plus index sizes, in memory (no per-call stat)."""
        return self._bytes

    @property
    def full(self) -> bool:
        """The store stops accepting NEW images past its byte cap (existing ones still count)."""
        return self._bytes >= self.max_bytes

    def _put(self, sub: str, cid: str, arr: np.ndarray, seen: set) -> None:
        """Write one PNG once per content id; no-op when the content was already written."""
        if cid in seen:
            return
        path = self.root / sub / cid[:2] / f"{cid}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _png_bytes(arr)
        path.write_bytes(data)
        self._bytes += len(data)
        seen.add(cid)

    def add_crop(self, kind: str, label: int, coarse: str, area: str, region: str,
                 x: int, y: int, w: int, h: int, bank: int | None, arr: np.ndarray) -> str | None:
        """Count one labelled crop; writes its PNG when the content is new and under the caps."""
        cid, key = content_id(arr), (kind, label, area)
        row = self._samples.get((*key, cid))
        if row is not None:
            row["count"] += 1
            return cid
        if cid not in self._seen and (self.full or len(self._per_key.get(key, ())) >= self.max_per_key):
            return None         # a NEW image refused: existing images keep counting, the cap holds
        self._put("images", cid, arr, self._seen)
        self._per_key.setdefault(key, set()).add(cid)
        self._samples[(*key, cid)] = {"id": cid, "kind": kind, "label": label, "coarse": coarse,
                                      "area": area, "region": region, "x": x, "y": y, "w": w, "h": h,
                                      "count": 1, "bank": bank}
        return cid

    def add_thumb(self, area: str, cell: str, pos, arr: np.ndarray) -> str | None:
        """Count one frame thumbnail under (area, cell); writes its PNG when new."""
        cid = content_id(arr)
        row = self._thumbs.get((area, cell, cid))
        if row is not None:
            row["count"] += 1
            return cid
        if cid not in self._tseen and (self.full or len(self._tseen) >= self.max_thumbs):
            return None
        self._put("thumbs", cid, arr, self._tseen)
        self._thumbs[(area, cell, cid)] = {"id": cid, "area": area, "cell": cell,
                                           "pos": list(pos) if pos is not None else None, "count": 1}
        return cid

    def flush(self) -> None:
        """Write samples.jsonl, thumbs.jsonl and meta.json atomically; index sizes count as bytes."""
        for name, rows in (("samples.jsonl", self._samples), ("thumbs.jsonl", self._thumbs)):
            text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows.values())
            write_atomic(self.root / name, lambda p: p.write_text(text, encoding="utf-8"))
            self._bytes += len(text.encode("utf-8"))
        doc = {"schema": 1, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "bytes": self._bytes,
               "caps": {"max_bytes": self.max_bytes, "max_per_key": self.max_per_key,
                        "max_thumbs": self.max_thumbs}}
        doc.update(self.meta)
        write_atomic(self.root / "meta.json",
                     lambda p: p.write_text(json.dumps(doc) + "\n", encoding="utf-8"))
