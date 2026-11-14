"""vision_relabel: semantic appended last, idempotent, backup once, dry-run safe, runs-only root."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from pokeagent.atlas.collision import ENTRY, TILESET_TABLE

ROOT = Path(__file__).resolve().parents[1]


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "vision_relabel_tool", ROOT / "tools" / "vision_relabel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_rom() -> bytes:
    """Tileset 2 with walkable id 7 and one all-7s block at 0x2000."""
    rom = bytearray(0xD000)
    e = TILESET_TABLE + ENTRY * 2
    rom[e] = 1
    rom[e + 1:e + 3] = (0x2000).to_bytes(2, "little")
    rom[e + 3:e + 5] = (0x3000).to_bytes(2, "little")
    rom[e + 5:e + 7] = (0x1000).to_bytes(2, "little")
    rom[e + 7:e + 11] = bytes([0xFF, 0xFF, 0xFF, 0xFF])       # no counters, no grass
    rom[0x1000:0x1002] = bytes([0x07, 0xFF])
    rom[0x2000:0x2010] = bytes([7] * 16)
    return bytes(rom)


def rows():
    return [{"id": "aa", "kind": "tile", "label": 7, "coarse": "terrain",
             "area": "m", "region": "r", "x": 0, "y": 0, "w": 8, "h": 8,
             "count": 4, "bank": 2},
            {"id": "bb", "kind": "sprite", "label": 13, "coarse": "npc",
             "area": "m", "region": "r", "x": 0, "y": 0, "w": 16, "h": 16,
             "count": 2, "bank": None},
            {"id": "cc", "kind": "tile", "label": 9, "coarse": "terrain",
             "area": "m", "region": "r", "x": 0, "y": 0, "w": 8, "h": 8,
             "count": 1, "bank": 2}]


def test_relabel_appends_semantic_last_and_is_idempotent():
    mod = _load_tool()
    tables = {2: {7: "walkable"}}
    out = mod.relabel([dict(r) for r in rows()], tables)
    assert [r["semantic"] for r in out] == ["walkable", "npc", "other"]
    assert all(list(r)[-1] == "semantic" for r in out)
    assert out[0]["count"] == 4 and out[2]["bank"] == 2        # other fields untouched
    again = mod.relabel(out, tables)
    assert [r["semantic"] for r in again] == ["walkable", "npc", "other"]
    assert all(list(r)[-1] == "semantic" for r in again)


def test_summarise_counts_per_kind_and_fallback():
    mod = _load_tool()
    text = mod.summarise(mod.relabel(rows(), {2: {7: "walkable"}}))
    lines = text.splitlines()
    assert any("tile" in ln and "walkable" in ln for ln in lines)
    assert any("sprite" in ln and "npc" in ln for ln in lines)
    assert lines[-1] == "tile rows fell back to other (no table or tile id): 1"


def test_main_writes_backup_once_and_dry_run_writes_nothing(tmp_path, monkeypatch):
    mod = _load_tool()
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs" / "vision" / "g"
    root.mkdir(parents=True)
    src = root / "samples.jsonl"
    src.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows()),
                   encoding="utf-8")
    original = src.read_bytes()
    rom = tmp_path / "fake.gb"
    rom.write_bytes(make_rom())
    argv = ["--root", str(root), "--rom", str(rom)]
    assert mod.main(argv + ["--dry-run"]) == 0
    assert src.read_bytes() == original
    assert not (root / "samples.jsonl.pre-semantic").exists()
    assert mod.main(argv) == 0
    backup = root / "samples.jsonl.pre-semantic"
    assert backup.read_bytes() == original
    first = src.read_text()
    assert all("semantic" in json.loads(ln) for ln in first.splitlines())
    assert mod.main(argv) == 0                          # idempotent, backup kept
    assert backup.read_bytes() == original
    assert src.read_text() == first
    assert not (root / "samples.jsonl.tmp").exists()


def test_main_refuses_a_root_outside_runs(tmp_path):
    mod = _load_tool()
    rom = tmp_path / "fake.gb"
    rom.write_bytes(make_rom())
    assert mod.main(["--root", str(tmp_path / "elsewhere"), "--rom", str(rom)]) == 2
